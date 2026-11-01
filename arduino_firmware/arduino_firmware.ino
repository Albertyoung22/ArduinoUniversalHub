/*
  Arduino High-Speed Non-Blocking Serial Controller
  Baud rate: 115200 bps
*/

String inputBuffer = "";

void setup() {
  Serial.begin(115200);
  inputBuffer.reserve(64);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println(F("ARDUINO_READY"));
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      if (inputBuffer.length() < 64) {
        inputBuffer += c;
      }
    }
  }
}

void processCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  int spaceIdx = cmd.indexOf(' ');
  String action = (spaceIdx == -1) ? cmd : cmd.substring(0, spaceIdx);
  String params = (spaceIdx == -1) ? "" : cmd.substring(spaceIdx + 1);
  params.trim();

  if (action == "PING") {
    Serial.println(F("PONG"));
  }
  else if (action == "RGB") { // RGB <r_pin> <g_pin> <b_pin> <r> <g> <b>
    int r_pin, g_pin, b_pin, r_val, g_val, b_val;
    if (sscanf(params.c_str(), "%d %d %d %d %d %d", &r_pin, &g_pin, &b_pin, &r_val, &g_val, &b_val) == 6) {
      analogWrite(r_pin, constrain(r_val, 0, 255));
      analogWrite(g_pin, constrain(g_val, 0, 255));
      analogWrite(b_pin, constrain(b_val, 0, 255));
      Serial.println(F("OK"));
    } else {
      Serial.println(F("ERR"));
    }
  }
  else if (action == "PINMODE") {
    int sp = params.indexOf(' ');
    if (sp == -1) {
      Serial.println(F("ERR"));
      return;
    }
    int pin = params.substring(0, sp).toInt();
    String modeStr = params.substring(sp + 1);
    modeStr.trim();
    if (modeStr == "OUTPUT") pinMode(pin, OUTPUT);
    else if (modeStr == "INPUT") pinMode(pin, INPUT);
    else if (modeStr == "INPUT_PULLUP") pinMode(pin, INPUT_PULLUP);
    Serial.println(F("OK"));
  }
  else if (action == "DW") { // DW <pin> <val>
    int sp = params.indexOf(' ');
    if (sp == -1) {
      Serial.println(F("ERR"));
      return;
    }
    int pin = params.substring(0, sp).toInt();
    int val = params.substring(sp + 1).toInt();
    pinMode(pin, OUTPUT);
    digitalWrite(pin, val ? HIGH : LOW);
    Serial.println(F("OK"));
  }
  else if (action == "DR") { // DR <pin>
    int pin = params.toInt();
    Serial.println(digitalRead(pin));
  }
  else if (action == "AW") { // AW <pin> <0-255>
    int sp = params.indexOf(' ');
    if (sp == -1) {
      Serial.println(F("ERR"));
      return;
    }
    int pin = params.substring(0, sp).toInt();
    int val = params.substring(sp + 1).toInt();
    pinMode(pin, OUTPUT);
    analogWrite(pin, constrain(val, 0, 255));
    Serial.println(F("OK"));
  }
  else if (action == "AR") { // AR <0-5>
    int pin = params.toInt();
    Serial.println(analogRead(A0 + pin));
  }
  else if (action == "STATUS") {
    Serial.println(F("STATUS: OK, UNO_ATM328P, BAUD=115200"));
  }
  else {
    Serial.println(F("ERR"));
  }
}
