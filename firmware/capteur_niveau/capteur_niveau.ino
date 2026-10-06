/*
  AquaSentinelle CI : capteur de niveau d'eau (option IoT, I1 à I10).
  ESP32 + capteur ultrason étanche JSN-SR04T fixé AU-DESSUS du caniveau ou du canal, pointé vers le fond.

  NON TESTÉ sur matériel : à valider sur banc (seau d'eau, I10) avant toute pose.

  Principe : mesure toutes les 10 min, envoi HTTP à l'API, puis sommeil profond (I2).
  Hauteur d'eau = HAUTEUR_CAPTEUR_CM - distance mesurée.
  Liaison : Wi-Fi ici pour le prototype ; en terrain, remplacer par un module GSM (SIM800L / SIM7600) ou LoRa (I3).
  Authentification : clé d'API dans l'en-tête X-Cle-API ; l'heure est fixée par le serveur (I7).
  Arrachement / vol (I6, I9) : si le capteur ne parle plus, le serveur le signale après 1 h de silence.

  Câblage JSN-SR04T : TRIG -> GPIO 5, ECHO -> GPIO 18 (via pont diviseur 5 V -> 3,3 V), VCC 5 V, GND.
  Batterie : pont diviseur 1:2 sur GPIO 34 pour lire la tension.
*/
#include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_NOM = "A_RENSEIGNER";
const char* WIFI_MDP = "A_RENSEIGNER";
const char* URL_API  = "http://192.168.1.20:8000/api/capteurs/CAP-ATT-01/mesures";  // BASE_URL du serveur
const char* CLE_API  = "A_RENSEIGNER";                                              // donnée à l'enregistrement

const int BROCHE_TRIG = 5, BROCHE_ECHO = 18, BROCHE_BATTERIE = 34;
const float HAUTEUR_CAPTEUR_CM = 120.0;       // distance capteur -> fond du caniveau, mesurée à la pose
const uint64_t SOMMEIL_US = 10ULL * 60ULL * 1000000ULL;   // 10 minutes

float distance_cm() {
  // médiane de 5 mesures : les gouttes et les déchets flottants donnent des valeurs aberrantes
  float m[5];
  for (int i = 0; i < 5; i++) {
    digitalWrite(BROCHE_TRIG, LOW); delayMicroseconds(2);
    digitalWrite(BROCHE_TRIG, HIGH); delayMicroseconds(20);
    digitalWrite(BROCHE_TRIG, LOW);
    long duree = pulseIn(BROCHE_ECHO, HIGH, 30000);
    m[i] = duree > 0 ? duree * 0.0343 / 2.0 : -1;
    delay(60);
  }
  for (int i = 0; i < 4; i++) for (int j = i + 1; j < 5; j++) if (m[j] < m[i]) { float t = m[i]; m[i] = m[j]; m[j] = t; }
  return m[2];
}

float batterie_v() {
  return analogReadMilliVolts(BROCHE_BATTERIE) * 2.0 / 1000.0;
}

void setup() {
  Serial.begin(115200);
  pinMode(BROCHE_TRIG, OUTPUT);
  pinMode(BROCHE_ECHO, INPUT);

  float d = distance_cm();
  float niveau = (d > 0) ? HAUTEUR_CAPTEUR_CM - d : -1;
  if (niveau < 0) niveau = 0;   // capteur aveuglé ou caniveau vide

  WiFi.begin(WIFI_NOM, WIFI_MDP);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(URL_API);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Cle-API", CLE_API);
    String corps = String("{\"niveau_cm\":") + String(niveau, 1) + ",\"batterie_v\":" + String(batterie_v(), 2) + "}";
    int code = http.POST(corps);
    Serial.printf("niveau %.1f cm -> HTTP %d\n", niveau, code);
    http.end();
  }
  WiFi.disconnect(true);
  esp_sleep_enable_timer_wakeup(SOMMEIL_US);   // veille profonde : quelques µA entre deux mesures
  esp_deep_sleep_start();
}

void loop() {}
