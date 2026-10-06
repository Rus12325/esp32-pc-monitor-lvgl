/*
 * STANDALONE font test — LVGL NOT involved.
 * Draws text with TFT_eSPI's built-in fonts in a loop.
 * If this is crisp, the panel+SPI+TFT fonts are fine and the problem is LVGL.
 * If this is also "boxes", then TFT font loading / color order is broken.
 */
#include <Arduino.h>
#include <TFT_eSPI.h>
#include <stdio.h>

TFT_eSPI tft = TFT_eSPI();

void setup() {
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);
  tft.init();
  tft.setRotation(1);
  tft.invertDisplay(false);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_YELLOW, TFT_BLACK);
  tft.setTextPadding(0);
}

void loop() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextFont(1); tft.setTextSize(3); tft.setCursor(4, 4);
  tft.println("FONT1 GLCD");
  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.setTextFont(2); tft.setTextSize(2); tft.setCursor(4, 60);
  tft.println("ABCDEFG abcdefg");
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextFont(4); tft.setTextSize(1); tft.setCursor(4, 100);
  tft.println("0123456789 123456");
  tft.setTextColor(TFT_RED, TFT_BLACK);
  tft.setTextFont(7); tft.setTextSize(1); tft.setCursor(4, 140);
  tft.println("FONT7 LARGE TEST 555");
  char buf[40]; sprintf(buf, "loop %lu", (unsigned long)millis() / 1000);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextFont(2); tft.setTextSize(2); tft.setCursor(4, 180);
  tft.println(buf);
  delay(1500);
}
