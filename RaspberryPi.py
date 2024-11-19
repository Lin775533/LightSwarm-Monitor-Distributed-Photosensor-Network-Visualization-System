import socket
import time
import threading
import RPi.GPIO as GPIO
from datetime import datetime
from collections import deque, defaultdict  # Added missing import
import numpy as np

import matplotlib
matplotlib.use('TkAgg')  # Must be before importing plt
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from queue import Queue
import tkinter as tk

# GPIO Setup
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# LED Pins
RED_LED = 27
GREEN_LED = 23
YELLOW_LED = 22
WHITE_LED = 24
RESET_BUTTON = 15

# Setup pins
for pin in [RED_LED, GREEN_LED, YELLOW_LED, WHITE_LED]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

GPIO.setup(RESET_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Network settings
UDP_PORT = 2910
BROADCAST_IP = '192.168.1.255'

class GraphData:
    def __init__(self):
        print("Initializing GraphData...")
        self.start_time = time.time()
        self.timestamps = deque(maxlen=30)
        self.readings = deque(maxlen=30)
        self.colors = deque(maxlen=30)
        self.master_times = defaultdict(float)
        self.master_start_times = {}
        self.current_master = None
        self.master_colors = {}
        self.last_update = time.time()
        
        # Add color setup
        self.color_list = ['red', 'blue', 'green', 'purple', 'orange', 'yellow']
        self.next_color_idx = 0
        
        # Create figure with two subplots
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(6, 4))
        self.fig.canvas.manager.set_window_title('LightSwarm Monitor')
        
        # Enable faster rendering
        self.fig.canvas.toolbar.set_message = lambda x: None
        self.fig.set_tight_layout(True)
        
        self.setup_plots()
        manager = plt.get_current_fig_manager()
        manager.window.wm_geometry("+0+0")
        
        # Initialize plots
        self.ax1.plot([], [])
        self.ax2.bar([], [])
        
        plt.ion()
        plt.show(block=False)
        plt.pause(0.1)

    def reset(self):
        """Thread-safe reset of graph data"""
        # Clear data
        self.timestamps.clear()
        self.readings.clear()
        self.colors.clear()
        self.master_times.clear()
        self.master_start_times.clear()
        self.current_master = None
        self.master_colors.clear()
        self.next_color_idx = 0
        self.start_time = time.time()
        
        try:
            # Clear plots
            self.ax1.cla()
            self.ax2.cla()
            
            # Reset to initial state
            self.setup_plots()
            
            # Draw empty plots
            self.ax1.plot([], [])
            self.ax2.bar([], [])
            
            # Update
            self.fig.canvas.draw_idle()
        except Exception as e:
            print(f"Error in reset: {e}")

    def setup_plots(self):
        """Set up the basic plot parameters"""
        try:
            # Configure photocell plot
            self.ax1.set_title('Photocell Readings (Last 30s)', fontsize=8)
            self.ax1.set_xlabel('Time (s)', fontsize=8)
            self.ax1.set_ylabel('Reading', fontsize=8)
            self.ax1.tick_params(labelsize=6)
            self.ax1.grid(True)
            self.ax1.set_ylim(0, 1023)
            self.ax1.set_xlim(0, 30)
            
            # Configure master times plot
            self.ax2.set_title('Master Device Times', fontsize=8)
            self.ax2.set_xlabel('Device IP', fontsize=8)
            self.ax2.set_ylabel('Time as Master (s)', fontsize=8)
            self.ax2.tick_params(labelsize=6)
            self.ax2.grid(True)
            self.ax2.set_ylim(0, 10)
            
            self.fig.tight_layout()
        except Exception as e:
            print(f"Error in setup_plots: {e}")

    def update_plots(self):
        try:
            # Clear existing plots
            self.ax1.cla()
            self.ax2.cla()
            
            # Reestablish basic plot parameters
            self.setup_plots()
            
            # If we have data, plot it
            if self.timestamps:
                times = np.array(list(self.timestamps)) - min(self.timestamps)
                readings = np.array(list(self.readings))
                
                # Plot readings
                for i in range(len(times)-1):
                    self.ax1.plot(times[i:i+2], readings[i:i+2], 
                                color=list(self.colors)[i], linewidth=2)
                
                # Plot bar chart if we have master data
                if self.master_times:
                    current_time = time.time()
                    master_data = self.master_times.copy()
                    
                    if self.current_master and self.current_master in self.master_start_times:
                        ongoing_duration = current_time - self.master_start_times[self.current_master]
                        master_data[self.current_master] = master_data.get(self.current_master, 0) + ongoing_duration
                    
                    ips = list(master_data.keys())
                    times = list(master_data.values())
                    bars = self.ax2.bar(range(len(ips)), times)
                    
                    for idx, (bar, ip) in enumerate(zip(bars, ips)):
                        bar.set_color(self.master_colors[ip])
                        self.ax2.text(idx, bar.get_height(), f'{bar.get_height():.1f}s',
                                    ha='center', va='bottom', fontsize=6)
                    
                    self.ax2.set_xticks(range(len(ips)))
                    self.ax2.set_xticklabels(ips, rotation=45, ha='right')
                
                # Add legend if we have masters
                if self.master_colors:
                    legend_elements = [plt.Line2D([0], [0], color=color, label=f'Master {ip}')
                                     for ip, color in self.master_colors.items()]
                    self.ax1.legend(handles=legend_elements, loc='upper right', fontsize=6)
            
            # Update the display
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
            
        except Exception as e:
            print(f"Error updating plots: {e}")

    def get_master_color(self, master_ip):
        if master_ip not in self.master_colors:
            self.master_colors[master_ip] = self.color_list[self.next_color_idx % len(self.color_list)]
            self.next_color_idx += 1
        return self.master_colors[master_ip]

    def update_data(self, timestamp, reading, master_ip):
        current_time = time.time()
        
        # Update master timing if master changed or for first master
        if master_ip != self.current_master:
            # Handle previous master's time if there was one
            if self.current_master:
                duration = current_time - self.master_start_times[self.current_master]
                self.master_times[self.current_master] += duration
                print(f"Master changed from {self.current_master} to {master_ip}")
            
            # Always set start time for new/current master
            self.master_start_times[master_ip] = current_time
            self.current_master = master_ip
            
            # Initialize master_times entry if it doesn't exist
            if master_ip not in self.master_times:
                self.master_times[master_ip] = 0.0
        
        # Always store the new reading
        self.timestamps.append(current_time)
        self.readings.append(reading)
        self.colors.append(self.get_master_color(master_ip))


                
    def on_key_press(self, event):
        if event.key == 'q':
            print("\nClosing application...")
            plt.close('all')
            if hasattr(self, 'lightswarm'):
                self.lightswarm.running = False
                self.lightswarm.cleanup()
            
class LightSwarm:
    def __init__(self):
        # Initialize tkinter root first
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the main window
        
        # Initialize matplotlib in main thread
        plt.ion()  # Turn on interactive mode
        
        # Socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', UDP_PORT))
        
        self.current_master = None
        self.running = True
        self.system_active = True
        
        # Initialize graph data after Tkinter root
        self.graph_data = GraphData()
        self.graph_data.lightswarm = self
        
        self.current_logfile = self.create_new_logfile()
        
        # Device tracking
        self.device_data = {}
        self.device_led_assignments = {}
        self.available_leds = [RED_LED, GREEN_LED, YELLOW_LED]
        
        # Start threads
        threading.Thread(target=self.receive_data, daemon=True).start()
        threading.Thread(target=self.handle_button, daemon=True).start()
        threading.Thread(target=self.update_leds, daemon=True).start()


    def update_gui(self):
        """Main GUI update function"""
        last_update = time.time()
        update_interval = 1.0  # 1 second

        while self.running:
            try:
                current_time = time.time()
                
                # Update GUI at fixed interval
                if current_time - last_update >= update_interval:
                    if self.system_active:
                        # Get current reading if available
                        if self.current_master and self.current_master in self.device_data:
                            reading = self.device_data[self.current_master]['reading']
                            ip_addr = self.device_data[self.current_master]['addr']
                            
                            # Update data and plots
                            self.graph_data.update_data(current_time, reading, ip_addr)
                        
                        # Always update plots
                        self.graph_data.update_plots()
                        
                    last_update = current_time
                
                # Keep GUI responsive
                self.root.update()
                plt.pause(0.01)  # Add small pause for matplotlib
                
            except Exception as e:
                if 'main thread' not in str(e):
                    print(f"Error updating GUI: {e}")
            
            if not self.running:
                break
            
    def receive_data(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                message = data.decode('utf-8')
                if message.startswith('MASTER:'):
                        print(f"Received: {message} from {addr}")
                self.handle_message(message, addr)
            except Exception as e:
                print(f"Error receiving data: {e}")

    def handle_message(self, message, addr):
            if not self.system_active:
                return
                
            if message.startswith('MASTER:'):
                try:
                    _, device_id, reading = message.split(':')
                    device_id = int(device_id)
                    reading = int(reading)
                    
                    # Update device data first
                    self.device_data[device_id] = {
                        'reading': reading,
                        'last_seen': time.time(),
                        'addr': addr[0]
                    }
                    
                    # Assign LED if needed
                    if device_id not in self.device_led_assignments and self.available_leds:
                        self.device_led_assignments[device_id] = self.available_leds.pop(0)
                        print(f"Assigned LED {self.device_led_assignments[device_id]} to Device {device_id}")
                    
                    # Handle master change more gracefully
                    if self.current_master is None or self.current_master != device_id:
                        # Log the master change
                        old_master = self.current_master
                        self.current_master = device_id
                        print(f"Master changed from {old_master} to {device_id}")
                    
                    # Log data after master update
                    self.log_data(device_id, reading)
                    
                    print(f"Master Device {device_id}: Reading = {reading}")
                except Exception as e:
                    print(f"Error handling master message: {e}")
    def send_reset(self):
        print("\nRESET initiated...")
        
        # First, turn off ALL LEDs
        for led in [RED_LED, GREEN_LED, YELLOW_LED, WHITE_LED]:
            GPIO.output(led, GPIO.LOW)
        
        # Send reset command to all ESPs first
        self.sock.sendto(b'RESET', (BROADCAST_IP, UDP_PORT))
        print("Reset command sent to ESPs")
        
        # Save current log file with summary
        if hasattr(self, 'current_logfile'):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.current_logfile, 'a') as f:
                f.write(f"\n=== Reset Summary at {timestamp} ===\n")
                f.write("Masters this session:\n")
                
                current_time = time.time()
                master_times = self.graph_data.master_times.copy()
                if self.graph_data.current_master:
                    duration = current_time - self.graph_data.master_start_times[self.graph_data.current_master]
                    master_times[self.graph_data.current_master] += duration
                
                for ip, duration in master_times.items():
                    f.write(f"IP: {ip}, Total Time: {duration:.2f} seconds\n")
                f.write("====================================\n\n")
        
        # Turn on Yellow LED for exactly 3 seconds
        GPIO.output(YELLOW_LED, GPIO.HIGH)
        time.sleep(3)
        GPIO.output(YELLOW_LED, GPIO.LOW)
        
        # Reset all device tracking
        self.device_data.clear()
        self.device_led_assignments.clear()
        self.available_leds = [RED_LED, GREEN_LED, YELLOW_LED]
        self.current_master = None
        
        # Create new log file
        self.current_logfile = self.create_new_logfile()
        print(f"Created new log file: {self.current_logfile}")
        
        # Reset graph data using thread-safe method
        self.graph_data.reset()
        
        # Set system to inactive
        self.system_active = False
        print("System is in reset state. Press button again to activate")

    def send_activate(self):
        print("Sending ACTIVATE command to all ESPs")
        
        # Clear any stale data to start fresh
        self.device_data.clear()
        self.device_led_assignments.clear()
        self.available_leds = [RED_LED, GREEN_LED, YELLOW_LED]
        self.current_master = None
        
        # Reset graph data using thread-safe method
        self.graph_data.reset()
        
        # Activate system
        self.system_active = True
        self.sock.sendto(b'ACTIVATE', (BROADCAST_IP, UDP_PORT))
        print("System reactivated - Starting fresh from zero")

    def update_leds(self):
        while self.running:
            try:
                if not self.system_active:
                    # When inactive, ensure ALL LEDs are off
                    for led in [RED_LED, GREEN_LED, YELLOW_LED, WHITE_LED]:
                        GPIO.output(led, GPIO.LOW)
                    time.sleep(0.1)
                    continue
                
                # System is active - normal LED operation
                if self.current_master and self.current_master in self.device_led_assignments:
                    led_pin = self.device_led_assignments[self.current_master]
                    if self.current_master in self.device_data:
                        reading = self.device_data[self.current_master]['reading']
                        flash_delay = self.calculate_flash_delay(reading)
                        GPIO.output(led_pin, GPIO.HIGH)
                        time.sleep(flash_delay)
                        GPIO.output(led_pin, GPIO.LOW)
                        time.sleep(flash_delay)
                
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Error in update_leds: {e}")


    def calculate_flash_delay(self, reading):
        return max(0.1, 1.0 - (reading / 1023.0 * 0.9))


    def create_new_logfile(self):
        # Create filename with current date and time
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'lightswarm_{timestamp}.log'
        
        # Initialize the new log file with header
        with open(filename, 'w') as f:
            f.write(f"=== New Session Started at {timestamp} ===\n")
            f.write("Format: timestamp, device_id, ip_address, reading, master_duration\n")
            f.write("===========================================\n\n")
        
        print(f"Created new log file: {filename}")
        return filename

    def handle_button(self):
        last_press_time = 0
        debounce_time = 0.5  # 500ms debounce time
        
        while self.running:
            current_state = GPIO.input(RESET_BUTTON)
            current_time = time.time()
            
            if current_state == GPIO.HIGH and (current_time - last_press_time) > debounce_time:
                last_press_time = current_time
                
                if self.system_active:
                    print("\nReset button pressed - Resetting system")
                    self.send_reset()  # This handles all reset functionality
                else:
                    print("\nReset button pressed - Activating system")
                    self.send_activate()
            
            time.sleep(0.1)  # Small delay to prevent CPU overuse

    def log_data(self, device_id, reading):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                ip_addr = self.device_data[device_id]['addr']
                master_duration = 0
                
                # Calculate master duration
                if ip_addr in self.graph_data.master_times:
                    master_duration = self.graph_data.master_times[ip_addr]
                    if ip_addr == self.graph_data.current_master:
                        master_duration += time.time() - self.graph_data.master_start_times[ip_addr]
                
                # Write to log file
                with open(self.current_logfile, 'a') as f:
                    f.write(f"{timestamp}, {device_id}, {ip_addr}, {reading}, {master_duration:.2f}\n")
                
            except Exception as e:
                print(f"Error logging data: {e}")



    def cleanup(self):
        print("\nCleaning up...")
        self.running = False
        for led in [RED_LED, GREEN_LED, YELLOW_LED, WHITE_LED]:
            GPIO.output(led, GPIO.LOW)
        GPIO.cleanup()
        self.sock.close()
        plt.close('all')
        print("Cleanup complete")

def main():
    try:
        swarm = LightSwarm()
        print("\nLightSwarm started with graphing. Press Ctrl+C to exit.")
        print("Reset button on GPIO 15")
        print("Press button once to reset, again to activate")
        print("Waiting for ESP devices...")
        
        # Run GUI update in main thread
        swarm.update_gui()
            
    except KeyboardInterrupt:
        print("\nShutdown requested...")
        swarm.cleanup()
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        swarm.cleanup()

if __name__ == "__main__":
        main()
