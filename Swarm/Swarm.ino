#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// WiFi settings
const char* ssid = "Jimmy&Tim";
const char* password = "1234567890";

// Network settings
WiFiUDP udp;
const unsigned int UDP_PORT = 2910;
IPAddress broadcastIP;  // Will be calculated based on network

// Device settings
const int LIGHT_SENSOR_PIN = A0;    
const int ONBOARD_LED = 2;          // Built-in LED for master indication
const int EXTERNAL_LED = 5;        // External LED for light level indication

// Protocol settings
const int PACKET_SIZE = 64;
char packetBuffer[PACKET_SIZE];
const unsigned long NETWORK_SILENCE = 100;    // 100ms silence before broadcasting
const unsigned long MASTER_TIMEOUT = 3000;    // 3s to determine master
unsigned long lastNetworkActivity = 0;
bool isActive = true;

// Device state
int deviceID;                       
int currentReading;                 
bool isMaster = false;             
struct SwarmData {
    int reading;
    unsigned long lastUpdate;
    int deviceID;
};
SwarmData swarmReadings[3];
int numDevices = 0;

void setup() {
    Serial.begin(9600);
    Serial.println("\nStarting LightSwarm Node...");
    
    // Initialize pins
    pinMode(ONBOARD_LED, OUTPUT);
    pinMode(EXTERNAL_LED, OUTPUT);
    digitalWrite(ONBOARD_LED, HIGH);  // Turn off (active LOW)
    analogWriteRange(1023);  // Set PWM range to match analogRead range
    analogWriteFreq(1000);   // Set PWM frequency to 1kHz for smooth dimming
    // Generate unique ID from MAC
    uint8_t mac[6];
    WiFi.macAddress(mac);
    deviceID = (mac[4] << 8) | mac[5];
    
    setupWiFi();
    udp.begin(UDP_PORT);
    
    Serial.printf("\nDevice ID: %d\n", deviceID);
    Serial.printf("Local IP: %s\n", WiFi.localIP().toString().c_str());
}

void setupWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected!");
    
    // Calculate broadcast IP based on network config
    IPAddress localIP = WiFi.localIP();
    IPAddress subnet = WiFi.subnetMask();
    for (int i = 0; i < 4; i++) {
        broadcastIP[i] = (localIP[i] | ~subnet[i]);
    }
}

void loop() {
    if (!isActive) {
        handleIncomingPackets();
        return;
    }
    
    // Simple direct reading
    currentReading = analogRead(LIGHT_SENSOR_PIN);
    
    // Direct mapping - LED brighter when more light detected
    int pwmValue = currentReading;  // Direct 1:1 mapping since both are 0-1023
    
    analogWrite(EXTERNAL_LED, pwmValue);
    
    // Debug print photoresistor reading every second
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint >= 1000) {  // Print every second
        Serial.println("----------------------");
        Serial.print("Light Sensor Reading: ");
        Serial.println(currentReading);
        Serial.print("PWM Value: ");
        Serial.println(pwmValue);
        Serial.print("LED Brightness %: ");
        Serial.print((pwmValue * 100) / 1023);
        Serial.println("%");
        Serial.print("Master Status: ");
        Serial.println(isMaster ? "YES" : "NO");
        lastPrint = millis();
    }
    
    handleIncomingPackets();
    
    // Check network silence
    if (millis() - lastNetworkActivity >= NETWORK_SILENCE) {
        broadcastReading();
    }
    
    updateMasterStatus();
}

void broadcastReading() {
    char message[32];
    snprintf(message, sizeof(message), "LIGHT:%d:%d", deviceID, currentReading);
    
    udp.beginPacketMulticast(broadcastIP, UDP_PORT, WiFi.localIP());
    udp.write(message);
    udp.endPacket();
    
    lastNetworkActivity = millis();
}

void updateSwarmData(int remoteID, int reading) {
    if (remoteID == deviceID) return;
    
    bool found = false;
    for (int i = 0; i < numDevices; i++) {
        if (swarmReadings[i].deviceID == remoteID) {
            swarmReadings[i].reading = reading;
            swarmReadings[i].lastUpdate = millis();
            found = true;
            break;
        }
    }
    
    if (!found && numDevices < 3) {
        swarmReadings[numDevices].deviceID = remoteID;
        swarmReadings[numDevices].reading = reading;
        swarmReadings[numDevices].lastUpdate = millis();
        numDevices++;
    }
}

// Add these at the top with other global variables
unsigned long masterClaimTime = 0;
unsigned long lastMasterBroadcast = 0;
const unsigned long MASTER_CLAIM_TIMEOUT = 500;  // 500ms waiting period
const unsigned long MASTER_BROADCAST_INTERVAL = 100;  // 100ms between master broadcasts

void updateMasterStatus() {
    unsigned long now = millis();
    bool shouldBeMaster = true;
    
    // Check all other devices
    for (int i = 0; i < numDevices; i++) {
        if (now - swarmReadings[i].lastUpdate < MASTER_TIMEOUT) {
            if (swarmReadings[i].reading > currentReading || 
               (swarmReadings[i].reading == currentReading && swarmReadings[i].deviceID > deviceID)) {
                shouldBeMaster = false;
                break;
            }
        }
    }
    
    // If we're currently master but shouldn't be, give up immediately
    if (isMaster && !shouldBeMaster) {
        isMaster = false;
        masterClaimTime = 0;
        digitalWrite(ONBOARD_LED, HIGH);  // Turn OFF
        Serial.println("Giving up master status");
        return;
    }
    
    // If we should be master but aren't yet
    if (shouldBeMaster && !isMaster) {
        // Start or continue waiting period
        if (masterClaimTime == 0) {
            masterClaimTime = now;
            Serial.println("Starting master claim period");
            return;
        }
        
        // Check if enough time has passed
        if (now - masterClaimTime >= MASTER_CLAIM_TIMEOUT) {
            // Final verification
            handleIncomingPackets();
            
            // Recheck all devices after waiting
            bool stillHighest = true;
            for (int i = 0; i < numDevices; i++) {
                if (now - swarmReadings[i].lastUpdate < MASTER_TIMEOUT) {
                    if (swarmReadings[i].reading > currentReading || 
                       (swarmReadings[i].reading == currentReading && swarmReadings[i].deviceID > deviceID)) {
                        stillHighest = false;
                        break;
                    }
                }
            }
            
            if (stillHighest) {
                isMaster = true;
                digitalWrite(ONBOARD_LED, LOW);  // Turn ON
                lastMasterBroadcast = 0;  // Force immediate broadcast
                Serial.println("Becoming master after verification");
                sendMasterUpdate();  // Announce immediately
            } else {
                masterClaimTime = 0;  // Reset claim time if we're no longer highest
            }
        }
    }
    
    // Regular master broadcasts
    if (isMaster && (now - lastMasterBroadcast >= MASTER_BROADCAST_INTERVAL)) {
        sendMasterUpdate();
        lastMasterBroadcast = now;
    }
}

void handleIncomingPackets() {
    int packetSize = udp.parsePacket();
    
    if (packetSize) {
        udp.read(packetBuffer, PACKET_SIZE);
        packetBuffer[packetSize] = 0;
        lastNetworkActivity = millis();
        
        if (strncmp(packetBuffer, "MASTER:", 7) == 0) {
            int remoteID, remoteReading;
            if (sscanf(packetBuffer, "MASTER:%d:%d", &remoteID, &remoteReading) == 2) {
                updateSwarmData(remoteID, remoteReading);
                
                // If they have a higher reading or equal reading with higher ID
                if (remoteReading > currentReading || 
                   (remoteReading == currentReading && remoteID > deviceID)) {
                    // Give up master status and reset claim time
                    isMaster = false;
                    masterClaimTime = 0;
                    digitalWrite(ONBOARD_LED, HIGH);  // Turn OFF
                    Serial.printf("Yielding to master: ID %d with reading %d\n", 
                                remoteID, remoteReading);
                }
            }
        }
        else if (strncmp(packetBuffer, "LIGHT:", 6) == 0 && isActive) {
            int remoteID, remoteReading;
            if (sscanf(packetBuffer, "LIGHT:%d:%d", &remoteID, &remoteReading) == 2) {
                updateSwarmData(remoteID, remoteReading);
                
                // If we see a higher reading, give up master status
                if (isMaster && (remoteReading > currentReading || 
                   (remoteReading == currentReading && remoteID > deviceID))) {
                    isMaster = false;
                    masterClaimTime = 0;
                    digitalWrite(ONBOARD_LED, HIGH);  // Turn OFF
                }
            }
        }
        else if (strncmp(packetBuffer, "RESET", 5) == 0) {
            handleReset();
        }
        else if (strncmp(packetBuffer, "ACTIVATE", 8) == 0) {
            handleActivate();
        }
    }
}
// Update this function to broadcast multiple times
void sendMasterUpdate() {
    char message[32];
    snprintf(message, sizeof(message), "MASTER:%d:%d", deviceID, currentReading);
    
    // Send message multiple times to ensure delivery
    for (int i = 0; i < 2; i++) {
        udp.beginPacketMulticast(broadcastIP, UDP_PORT, WiFi.localIP());
        udp.write(message);
        udp.endPacket();
        delay(2);  // Small delay between sends
    }
    
    lastNetworkActivity = millis();
}

void handleReset() {
    isActive = false;
    numDevices = 0;
    isMaster = false;
    masterClaimTime = 0;
    digitalWrite(ONBOARD_LED, HIGH);  // Turn off onboard LED
    analogWrite(EXTERNAL_LED, 0);     // Turn off external LED
}


void handleActivate() {
    isActive = true;
}