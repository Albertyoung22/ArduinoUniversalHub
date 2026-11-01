// Arduino Uno USB Passthrough to Webduino Fly ESP8266
void setup() {
  pinMode(0, INPUT);
  pinMode(1, INPUT);
}

void loop() {
  // Empty loop: ATmega328P pins 0 & 1 remain High-Z (input)
  // allowing PC USB to directly communicate with Webduino Fly ESP8266
}

