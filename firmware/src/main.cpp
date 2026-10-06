/*
 * ESP32-2432S028 (ST7789V2, 240x320; XPT2046 touch) — PC monitor/control.
 * Рендер полностью на TFT_eSPI (без LVGL) — детерминированный текст/графика.
 * Транспорт: Serial USB (CH340) 115200, JSON-строки через '\n' в обе стороны.
 */
#include <Arduino.h>
#include <SPI.h>
#include <XPT2046_Touchscreen.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include "config.h"

#define TOUCH_CLK  25
#define TOUCH_MISO 39
#define TOUCH_MO   32
#define TOUCH_CS   33
#define TOUCH_IRQ  36
SPIClass touchSPI(HSPI);
XPT2046_Touchscreen ts(TOUCH_CS, TOUCH_IRQ);

TFT_eSPI tft = TFT_eSPI();

// ---------------- data ----------------
struct Row { char name[14]; float v; };
struct {
  float cpuT=0, cpuLoad=0; bool hasCpu=false;
  float gpuT=0, gpuLoad=0; bool hasGpu=false;
  Row storage[4]; int nStorage=0;
  Row fans[4];    int nFans=0;
  char apps[4][14]; int nApps=0;
} pc;

uint32_t lastPacketMs = 0;
String rxLine;

// ---------------- button model ----------------
struct Btn { int16_t x, y, w, h; const char* label; uint16_t color; int action; };
// action: <0 = control cmd index; >=0 = launch idx
enum { A_SLEEP=0, A_POWER, A_VOLD, A_VOLU, A_MUTE, A_PLAY, A_BASE_LAUNCH=100 };

// laid out at runtime into two rows
Btn ctrls[6];   // power/sleep/vol/play/vol+/mute
Btn apps[4];    // dynamic quick-launch
int nAppsOn = 0;

void layout();
void refresh();

// ---------------- standby + history ----------------
uint32_t lastAct = 0;         // последнее касание/событие (для затемнения)
bool     dimmed  = false;
uint32_t lastClockSec = 0;    // для будильника в дежурном режиме

#define HIST 60
float hCpu[HIST]; float hGpu[HIST]; uint8_t hFilled=0; int hHead=0; // кольцевой буфер ~ раз в сек
uint32_t lastHistMs = 0;

bool everLinked = false;
char curTime[10] = "--:--";        // HH:MM от агента (для будильника в дежурном режиме)

void pushHistory(){
  hCpu[hHead]=pc.cpuT; hGpu[hHead]=pc.gpuT;
  hHead=(hHead+1)%HIST; if(hFilled<HIST)hFilled++;
}

void setBacklight(int duty){        // duty 0..255 (TFT_BL = 21)
#ifdef TFT_BL
  analogWrite(TFT_BL, duty);
#endif
}

char dimLastTime[10] = "";
uint16_t CLOCK_CY = 118;   // вертикальный центр часов

void dimFrame(){           // рисуется один раз при входе в дежурный режим
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(tft.color565(50,50,66), TFT_BLACK);
  tft.setTextFont(2); tft.setTextSize(1); tft.setTextDatum(MC_DATUM);
  tft.drawString("touch to wake", 160, 210);
  tft.setTextDatum(TL_DATUM);
  dimLastTime[0] = 0;      // заставим перерисовать часы
}

void dimDrawTime(){        // перерисовывает только зону часов (без мерцания фона)
  tft.fillRect(0, CLOCK_CY-30, 320, 60, TFT_BLACK);
  tft.setTextColor(tft.color565(120,120,150), TFT_BLACK);
  tft.setTextFont(7); tft.setTextSize(2); tft.setTextDatum(MC_DATUM);
  tft.drawString(curTime, 160, CLOCK_CY);
  tft.setTextDatum(TL_DATUM);
  strlcpy(dimLastTime, curTime, sizeof(dimLastTime));
}

void enterDim(){ dimmed=true; setBacklight(90); dimFrame(); dimDrawTime(); }
void wakeScreen(){ dimmed=false; lastAct=millis(); setBacklight(255); layout(); refresh(); }

void initCtrlButtons() {
  const int y=154, h=30, w=48, gap=(320-6*w)/5;
  const char* L[6]={"Power","Sleep","Vol-","Play","Vol+","Mute"};
  uint16_t C[6]={0xf810,0xfd20,0x8631,0x4e45,0x8631,0x632c};
  int A[6]={A_POWER,A_SLEEP,A_VOLD,A_PLAY,A_VOLU,A_MUTE};
  for (int i=0;i<6;i++){ ctrls[i]={ (int16_t)(i*(w+gap)), y, w, h, L[i], C[i], A[i] }; }
}

// ---------------- drawing helpers ----------------
uint16_t BG   = 0x0000;
void bar(int x,int y,int w,int h,int pct,uint16_t bg,uint16_t fg){
  tft.fillRect(x,y,w,h,bg);
  int fw = constrain(map(pct,0,100,0,w-2),0,w-2);
  if (fw>0) tft.fillRect(x+1,y+1,fw,h-2,fg);
}
void text(int x,int y,const char* s,uint16_t c,uint8_t font,uint8_t sz=1){
  tft.setTextFont(font); tft.setTextSize(sz); tft.setTextColor(c, BG);
  tft.setCursor(x,y); tft.print(s);
}
uint16_t tempColor(float t){ return t>80?0xf810:(t>65?0xfd20:0x07e0); }

void drawCard(const char* title,int x,int y,int w,int h,float t,float load,bool has){
  tft.fillRoundRect(x,y,w,h,6,0x18e7);
  tft.drawRoundRect(x,y,w,h,6,0x39e7);
  text(x+6,y+3,title,0xffffff,2,1);            // 3..19
  if (has){
    tft.setTextColor(tempColor(t),0x18e7); tft.setTextFont(7); tft.setTextSize(1);
    tft.setTextDatum(TC_DATUM);
    char num[8]; snprintf(num,sizeof(num),"%dC",(int)(t+0.5f));
    tft.drawString(num, x+w/2, y+16);           // число сверху (16..40)
    tft.setTextColor(0x8aeb,0x18e7); tft.setTextFont(2); tft.setTextSize(1);
    char lb[16]; snprintf(lb,sizeof(lb),"load %d%%",(int)load);
    tft.drawString(lb, x+w/2, y+62);            // слова ниже (62..76)
    bar(x+8, y+78, w-16, 6, (int)load, 0x0841, 0x4e45);  // полоса у низа (78..84)
    tft.setTextDatum(TL_DATUM);
  } else {
    tft.setTextColor(0x7bef,0x18e7); tft.setTextFont(4); tft.setTextSize(1);
    tft.setTextDatum(TC_DATUM);
    tft.drawString("no data", x+w/2, y+40);
    tft.setTextDatum(TL_DATUM);
  }
}

void drawBtn(const Btn& b, bool pressed){
  uint16_t col = pressed ? 0xffff : b.color;
  uint16_t txt = pressed ? 0x0000 : 0xffff;
  tft.fillRoundRect(b.x,b.y,b.w,b.h,5,b.color);
  if (pressed) tft.drawRoundRect(b.x,b.y,b.w,b.h,5,0xffff);
  tft.setTextColor(txt,b.color); tft.setTextFont(2); tft.setTextSize(1);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(b.label, b.x+b.w/2, b.y+b.h/2);
  tft.setTextDatum(TL_DATUM);
}

void drawApps(){
  for(int i=0;i<nAppsOn;i++) drawBtn(apps[i], false);
  if (nAppsOn==0){ text(4,190,"quick-launch: edit apps.json",0x7bef,1,1); }
}

void layout(){
  tft.fillScreen(BG);
  initCtrlButtons();
  for (auto &b: ctrls) drawBtn(b,false);
  drawApps();
}

void drawSpark(int x,int y,int w,int h){
  tft.drawRoundRect(x,y,w,h,3,0x3165);
  if (hFilled<2){ text(x+4,y+h/2-7,"collecting...",0x7bef,1,1); return; }
  auto plot=[&](float*buf,uint16_t col){
    int prevx=0,prevy=0;
    for(int i=0;i<hFilled;i++){
      int idx=(hHead-hFilled+i+HIST)%HIST;
      float v=buf[idx]; if(v<20)v=20; if(v>100)v=100;
      int px=x+1 + i*(w-2)/(HIST-1);
      int py=y+h-1 - (int)((v-20)/80.0*(h-2));
      if(i>0) tft.drawLine(prevx,prevy,px,py,col);
      prevx=px; prevy=py;
    }
  };
  plot(hCpu,0xfd20);   // CPU — янтарный
  plot(hGpu,0x07e0);   // GPU — зелёный
}

void refresh(){
  bool linked = (millis()-lastPacketMs) < LINK_TIMEOUT_MS;
  const char* hdr; uint16_t hc;
  if (linked){ hdr="PC: connected"; hc=0x4e45; }
  else if (everLinked){ hdr="PC: link lost"; hc=0xf810; }
  else { hdr="waiting for PC data..."; hc=0x7bef; }
  text(4,0,hdr,hc,2,1);

  drawCard("CPU",6,18,150,86, pc.cpuT, pc.cpuLoad, linked&&pc.hasCpu);
  drawCard("GPU",164,18,150,86, pc.gpuT, pc.gpuLoad, linked&&pc.hasGpu);

  // полоса: слева график температур, справа компактные подписи
  tft.fillRect(0,108,320,40,BG);
  drawSpark(4,110,180,34);
  text(188,110,"CPU",0xfd20,1,1);
  text(188,126,"GPU",0x07e0,1,1);
  int yy=110;
  for(int i=0;i<pc.nFans && i<2;i++){
    int r=(int)(pc.fans[i].v+0.5f); if(r<=0) continue;
    char s[22]; snprintf(s,sizeof(s),"%s %d",pc.fans[i].name,r);
    text(232,yy,s,0xa5a6,1,1); yy+=16;
  }
  for(int i=0;i<pc.nStorage && i<2 && yy<140;i++){
    char s[22]; snprintf(s,sizeof(s),"%s %dC",pc.storage[i].name,(int)(pc.storage[i].v+0.5f));
    text(232,yy,s,0xa5a6,1,1); yy+=16;
  }
}

// ---------------- commands ----------------
void sendCmd(const char* j){ Serial.print(j); Serial.println(); }
void doAction(int a){
  if (a==A_POWER) sendCmd("{\"cmd\":\"shutdown\"}");
  else if (a==A_SLEEP) sendCmd("{\"cmd\":\"sleep\"}");
  else if (a==A_VOLD) sendCmd("{\"cmd\":\"vol_down\"}");
  else if (a==A_VOLU) sendCmd("{\"cmd\":\"vol_up\"}");
  else if (a==A_MUTE) sendCmd("{\"cmd\":\"mute\"}");
  else if (a==A_PLAY) sendCmd("{\"cmd\":\"play\"}");
  else if (a>=A_BASE_LAUNCH){
    char b[40]; snprintf(b,sizeof(b),"{\"cmd\":\"launch\",\"idx\":%d}",a-A_BASE_LAUNCH); sendCmd(b);
  }
}

// ---------------- telemetry parse ----------------
void applyTelemetry(JsonDocument& d){
  if (!d["cpu"].isNull()){ pc.hasCpu=true; pc.cpuT=d["cpu"]["t"]|0.0f; pc.cpuLoad=d["cpu"]["load"]|0.0f; }
  if (!d["gpu"].isNull()){ pc.hasGpu=true; pc.gpuT=d["gpu"]["t"]|0.0f; pc.gpuLoad=d["gpu"]["load"]|0.0f; }
  pc.nStorage=0;
  for (JsonVariant v: d["storage"].as<JsonArray>()){
    if(pc.nStorage>=4)break; strlcpy(pc.storage[pc.nStorage].name,v["name"]|"Disk",14);
    pc.storage[pc.nStorage].v=v["t"]|0.0f; pc.nStorage++; }
  pc.nFans=0;
  for (JsonVariant v: d["fans"].as<JsonArray>()){
    if(pc.nFans>=4)break; strlcpy(pc.fans[pc.nFans].name,v["name"]|"Fan",14);
    pc.fans[pc.nFans].v=v["rpm"]|0.0f; pc.nFans++; }
  {
    int n=0; char la[4][14]={{0}};
    for(JsonVariant v: d["apps"].as<JsonArray>()){ if(n>=4)break; strlcpy(la[n],v["label"]|"App",14); n++; }
    if(n>0 && (n!=nAppsOn || memcmp(la,pc.apps,sizeof(la))!=0)){
      nAppsOn=n; memcpy(pc.apps,la,sizeof(la));
      const int y=188,h=30; int w = n>0? min(80,(320-(n-1)*6)/n):80; int gap=6;
      for(int i=0;i<n;i++){ apps[i]={(int16_t)(i*(w+gap)),y,w,h,pc.apps[i],0x3165,A_BASE_LAUNCH+i}; }
      tft.fillRect(0,186,320,34,BG); drawApps();
    }
  }
  const char* tm = d["time"] | (const char*)nullptr;
  if (tm){ strlcpy(curTime, tm, sizeof(curTime)); }
  everLinked = true;
  lastPacketMs=millis();
}

void pumpSerial(){
  while (Serial.available()){
    char ch=(char)Serial.read();
    if(ch=='\n'){ if(rxLine.length()){ JsonDocument d; if(!deserializeJson(d,rxLine)) applyTelemetry(d); rxLine=""; } }
    else if(rxLine.length()<512) rxLine+=ch;
  }
}

// ---------------- touch ----------------
struct Hit { int x,y; };
bool readTouch(Hit& h){
  if(!ts.touched()) return false;
  TS_Point p=ts.getPoint();
  int x=map(constrain(p.x,350,3760),350,3760,0,319);
  int y=map(constrain(p.y,350,3760),350,3760,0,239);
  h.x=constrain(x,0,319); h.y=constrain(y,0,239);
  return true;
}
bool inBtn(const Btn& b,int x,int y){ return x>=b.x&&x<b.x+b.w&&y>=b.y&&y<b.y+b.h; }
void handlePress(const Hit& h){
  for(auto&b:ctrls) if(inBtn(b,h.x,h.y)){ drawBtn(b,true); doAction(b.action); delay(120); drawBtn(b,false); return; }
  for(int i=0;i<nAppsOn;i++) if(inBtn(apps[i],h.x,h.y)){ drawBtn(apps[i],true); doAction(apps[i].action); delay(120); drawBtn(apps[i],false); return; }
}

void setup(){
  Serial.begin(SERIAL_BAUD);
  pinMode(TFT_BL,OUTPUT); digitalWrite(TFT_BL,HIGH);
  tft.init(); tft.setRotation(DISPLAY_ROTATION); tft.invertDisplay(DISPLAY_INVERT);
  tft.setTextDatum(TL_DATUM);
  touchSPI.begin(TOUCH_CLK,TOUCH_MISO,TOUCH_MO,TOUCH_CS);
  ts.begin(touchSPI); ts.setRotation(1);
  BG=tft.color565(8,12,20);
  layout();
  lastAct=millis();
  Serial.println("{\"hello\":\"esp32\"}");
}

void loop(){
  static uint32_t lastRf=0;
  pumpSerial();
  Hit h;
  bool touched = readTouch(h);

  if (dimmed){
    if (touched){ wakeScreen(); }
    else if (strcmp(curTime, dimLastTime) != 0){ dimDrawTime(); }
    delay(120); return;
  }

  if (touched){ lastAct=millis(); handlePress(h); while(ts.touched()) delay(5); }
  if (DIM_AFTER_MS>0 && millis()-lastAct>=DIM_AFTER_MS){ enterDim(); return; }

  if (millis()-lastHistMs>=1000){ lastHistMs=millis(); if(everLinked) pushHistory(); }
  if (millis()-lastRf>=UI_REFRESH_MS){ lastRf=millis(); refresh(); }
  delay(3);
}
