//+------------------------------------------------------------------+
//|                                             ORB_Live.mq5         |
//|                        Opening Range Breakout — Live Trading EA   |
//|                        Translated from orb_live.py                |
//+------------------------------------------------------------------+
#property copyright "shayanghad0"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+
input group "=== Strategy ==="
input int      InpRangeStartH  = 9;       // Range Start Hour (NY)
input int      InpRangeStartM  = 30;      // Range Start Minute (NY)
input int      InpRangeEndH    = 9;       // Range End Hour (NY)
input int      InpRangeEndM    = 36;      // Range End Minute (NY)
input int      InpTradeStartH  = 9;       // Trade Start Hour (NY)
input int      InpTradeStartM  = 36;      // Trade Start Minute (NY)
input int      InpTradeEndH    = 11;      // Trade End Hour (NY)
input int      InpTradeEndM    = 30;      // Trade End Minute (NY)

input group "=== Risk ==="
input double   InpTP1Pct       = 0.0025;  // TP1 % (0.25%)
input double   InpTP2Pct       = 0.005;   // TP2 % (0.50%)
input double   InpSLPct        = 0.0025;  // SL % (0.25%)
input double   InpLots         = 0.02;    // Lot Size
input int      InpMagic        = 202609;  // Magic Number
input int      InpSlippage     = 30;      // Slippage (points)

//+------------------------------------------------------------------+
//| STATE ENUM                                                        |
//+------------------------------------------------------------------+
enum ENUM_ORB_STATE
{
   STATE_IDLE       = 0,  // IDLE
   STATE_BUILDING   = 1,  // BUILDING
   STATE_WAIT_BREAK = 2,  // WAIT_BREAK
   STATE_HALF_OPEN  = 3,  // HALF_OPEN
   STATE_TRAIL      = 4,  // TRAIL
   STATE_DONE       = 5   // DONE
};

//+------------------------------------------------------------------+
//| GLOBALS                                                           |
//+------------------------------------------------------------------+
CTrade         trade;
ENUM_ORB_STATE g_state         = STATE_IDLE;
datetime       g_currentDate   = 0;
datetime       g_lastBarTime   = 0;
int            g_tickCount     = 0;

// ORB range
double         g_orbHigh       = 0;
double         g_orbLow        = 0;
bool           g_rangeBuilding = false;
bool           g_rangeLocked   = false;

// Trade
bool           g_tradeLong     = false;
double         g_entryPrice    = 0;
double         g_tp1Price      = 0;
double         g_tp2Price      = 0;
double         g_slPrice       = 0;
 ulong         g_ticket        = 0;
double         g_initialVolume = 0;
double         g_currentVolume = 0;

// Tracking
bool           g_tp1Hit        = false;
bool           g_tp2Hit        = false;
bool           g_dayDone       = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   Print("+----------------------------------------------+");
   Print("|     ORB LIVE EA — MetaTrader 5               |");
   Print("|  Opening Range Breakout · New York Session   |");
   Print("+----------------------------------------------+");
   PrintFormat("  Range: %02d:%02d — %02d:%02d NY", InpRangeStartH, InpRangeStartM, InpRangeEndH, InpRangeEndM);
   PrintFormat("  Trade: %02d:%02d — %02d:%02d NY", InpTradeStartH, InpTradeStartM, InpTradeEndH, InpTradeEndM);
   PrintFormat("  TP1: +%.2f%%  TP2: +%.2f%%  SL: -%.2f%%",
               InpTP1Pct * 100, InpTP2Pct * 100, InpSLPct * 100);
   PrintFormat("  Lots: %.2f  Magic: %d", InpLots, InpMagic);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("ORB EA deinitialized.");
}

//+------------------------------------------------------------------+
//| HELPER: Get current NY time (UTC-4 for EDT)                      |
//+------------------------------------------------------------------+
datetime GetNYTime()
{
   datetime utc = TimeCurrent();
   // EDT = UTC-4 (September 2026 is EDT)
   // For DST-safe version, you could use TimeTradeServer() + offset
   // but for simplicity, hardcoded UTC-4 like the Python bot
   return utc - 4 * 3600;
}

//+------------------------------------------------------------------+
//| HELPER: Extract time-of-day from datetime                        |
//+------------------------------------------------------------------+
MqlDateTime GetTimeComponents(datetime dt)
{
   MqlDateTime s;
   TimeToStruct(dt, s);
   return s;
}

//+------------------------------------------------------------------+
//| HELPER: Check if time is in a window                             |
//+------------------------------------------------------------------+
bool IsInWindow(MqlDateTime &t, int startH, int startM, int endH, int endM)
{
   int tMin = t.hour * 60 + t.min;
   int sMin = startH * 60 + startM;
   int eMin = endH * 60 + endM;
   return (tMin >= sMin && tMin < eMin);
}

//+------------------------------------------------------------------+
//| HELPER: Get current bid price                                    |
//+------------------------------------------------------------------+
double GetBid()
{
   MqlTick tick;
   if(SymbolInfoTick(_Symbol, tick))
      return tick.bid;
   return 0;
}

//+------------------------------------------------------------------+
//| HELPER: Get current ask price                                    |
//+------------------------------------------------------------------+
double GetAsk()
{
   MqlTick tick;
   if(SymbolInfoTick(_Symbol, tick))
      return tick.ask;
   return 0;
}

//+------------------------------------------------------------------+
//| HELPER: Get last M1 bar time                                     |
//+------------------------------------------------------------------+
datetime GetLastM1BarTime()
{
   datetime times[1];
   if(CopyTime(_Symbol, PERIOD_M1, 0, 1, times) == 1)
      return times[0];
   return 0;
}

//+------------------------------------------------------------------+
//| HELPER: Get last two M1 bars                                     |
//+------------------------------------------------------------------+
bool GetLastTwoBars(double &prevClose, double &currClose,
                    double &prevHigh, double &currHigh,
                    double &prevLow,  double &currLow)
{
   MqlRates rates[2];
   if(CopyRates(_Symbol, PERIOD_M1, 0, 2, rates) < 2)
      return false;

   prevClose = rates[0].close;
   prevHigh  = rates[0].high;
   prevLow   = rates[0].low;
   currClose = rates[1].close;
   currHigh  = rates[1].high;
   currLow   = rates[1].low;
   return true;
}

//+------------------------------------------------------------------+
//| HELPER: Check for new M1 bar                                     |
//+------------------------------------------------------------------+
bool IsNewM1Bar()
{
   datetime t = GetLastM1BarTime();
   if(t != g_lastBarTime && t != 0)
   {
      g_lastBarTime = t;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| LOG                                                               |
//+------------------------------------------------------------------+
void Log(string msg)
{
   MqlDateTime ny = GetTimeComponents(GetNYTime());
   PrintFormat("[%02d:%02d:%03d] %s", ny.hour, ny.min, ny.sec, msg);
}

//+------------------------------------------------------------------+
//| CHECK NEW DAY                                                     |
//+------------------------------------------------------------------+
void CheckNewDay()
{
   MqlDateTime ny = GetTimeComponents(GetNYTime());
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", ny.year, ny.mon, ny.day));

   if(g_currentDate != today)
   {
      g_currentDate = today;
      ResetDay();
   }
}

//+------------------------------------------------------------------+
//| RESET DAY                                                         |
//+------------------------------------------------------------------+
void ResetDay()
{
   g_state         = STATE_IDLE;
   g_orbHigh       = 0;
   g_orbLow        = 0;
   g_rangeBuilding = false;
   g_rangeLocked   = false;
   g_tradeLong     = false;
   g_entryPrice    = 0;
   g_tp1Price      = 0;
   g_tp2Price      = 0;
   g_slPrice       = 0;
   g_ticket        = 0;
   g_initialVolume = 0;
   g_currentVolume = 0;
   g_tp1Hit        = false;
   g_tp2Hit        = false;
   g_dayDone       = false;
   g_lastBarTime   = 0;

   Log("Day reset — waiting for new session");
}

//+------------------------------------------------------------------+
//| UPDATE ORB RANGE                                                  |
//+------------------------------------------------------------------+
void UpdateORBRange(double barHigh, double barLow, MqlDateTime &t)
{
   bool inRange = IsInWindow(t, InpRangeStartH, InpRangeStartM, InpRangeEndH, InpRangeEndM);

   if(inRange && !g_rangeLocked)
   {
      if(g_orbHigh == 0)
      {
         g_orbHigh = barHigh;
         g_orbLow  = barLow;
         g_rangeBuilding = true;
         g_state = STATE_BUILDING;
         Log(StringFormat("Range started — High: %.5f  Low: %.5f", g_orbHigh, g_orbLow));
      }
      else
      {
         if(barHigh > g_orbHigh) g_orbHigh = barHigh;
         if(barLow  < g_orbLow)  g_orbLow  = barLow;
      }
   }

   if(!inRange && g_rangeBuilding && !g_rangeLocked)
   {
      g_rangeLocked   = true;
      g_rangeBuilding = false;
      g_state = STATE_WAIT_BREAK;
      Log(StringFormat("Range LOCKED — High: %.5f  Low: %.5f", g_orbHigh, g_orbLow));
      Log("Waiting for breakout...");
   }
}

//+------------------------------------------------------------------+
//| SEND ORDER                                                        |
//+------------------------------------------------------------------+
bool SendOrder(ENUM_ORDER_TYPE orderType, double volume)
{
   double price;
   if(orderType == ORDER_TYPE_BUY)
      price = GetAsk();
   else
      price = GetBid();

   if(!trade.PositionOpen(_Symbol, orderType, volume, price, 0, 0, "ORB_LIVE"))
   {
      Log(StringFormat("ERROR: Order failed — %s (code %d)",
           trade.ResultComment(), trade.ResultRetcode()));
      return false;
   }

   g_ticket = trade.ResultOrder();
   Log(StringFormat("Order FILLED — Ticket: %I64u  Volume: %.2f  Price: %.5f",
        g_ticket, volume, trade.ResultPrice()));
   g_state = STATE_HALF_OPEN;
   return true;
}

//+------------------------------------------------------------------+
//| ENTER LONG                                                        |
//+------------------------------------------------------------------+
void EnterLong(double price)
{
   g_tradeLong     = true;
   g_entryPrice    = price;
   g_tp1Price      = g_entryPrice * (1 + InpTP1Pct);
   g_tp2Price      = g_entryPrice * (1 + InpTP2Pct);
   g_slPrice       = g_entryPrice * (1 - InpSLPct);
   g_initialVolume = InpLots;
   g_currentVolume = InpLots;
   g_tp1Hit        = false;
   g_tp2Hit        = false;

   Log(StringFormat("LONG ENTRY @ %.5f", g_entryPrice));
   Log(StringFormat("  TP1: %.5f (+0.25%%)  TP2: %.5f (+0.50%%)  SL: %.5f (-0.25%%)",
       g_tp1Price, g_tp2Price, g_slPrice));

   SendOrder(ORDER_TYPE_BUY, InpLots);
}

//+------------------------------------------------------------------+
//| ENTER SHORT                                                       |
//+------------------------------------------------------------------+
void EnterShort(double price)
{
   g_tradeLong     = false;
   g_entryPrice    = price;
   g_tp1Price      = g_entryPrice * (1 - InpTP1Pct);
   g_tp2Price      = g_entryPrice * (1 - InpTP2Pct);
   g_slPrice       = g_entryPrice * (1 + InpSLPct);
   g_initialVolume = InpLots;
   g_currentVolume = InpLots;
   g_tp1Hit        = false;
   g_tp2Hit        = false;

   Log(StringFormat("SHORT ENTRY @ %.5f", g_entryPrice));
   Log(StringFormat("  TP1: %.5f (-0.25%%)  TP2: %.5f (-0.50%%)  SL: %.5f (+0.25%%)",
       g_tp1Price, g_tp2Price, g_slPrice));

   SendOrder(ORDER_TYPE_SELL, InpLots);
}

//+------------------------------------------------------------------+
//| CHECK BREAKOUT                                                    |
//+------------------------------------------------------------------+
void CheckBreakout()
{
   if(g_state != STATE_WAIT_BREAK) return;
   if(g_dayDone) return;

   MqlDateTime ny = GetTimeComponents(GetNYTime());
   if(!IsInWindow(ny, InpTradeStartH, InpTradeStartM, InpTradeEndH, InpTradeEndM))
      return;

   double prevClose, currClose, prevHigh, currHigh, prevLow, currLow;
   if(!GetLastTwoBars(prevClose, currClose, prevHigh, currHigh, prevLow, currLow))
      return;

   // Bullish breakout: close crosses above orb_high
   if(currClose > g_orbHigh && prevClose <= g_orbHigh)
   {
      EnterLong(currClose);
   }
   // Bearish breakout: close crosses below orb_low
   else if(currClose < g_orbLow && prevClose >= g_orbLow)
   {
      EnterShort(currClose);
   }
}

//+------------------------------------------------------------------+
//| CLOSE POSITION (partial or full)                                  |
//+------------------------------------------------------------------+
bool ClosePosition(double volume = 0)
{
   if(g_ticket == 0)
   {
      Log("ERROR: No ticket to close");
      return false;
   }

   if(!PositionSelectByTicket(g_ticket))
   {
      Log(StringFormat("WARNING: Position %I64u not found — may already be closed", g_ticket));
      g_ticket   = 0;
      g_dayDone  = true;
      g_state    = STATE_DONE;
      return true;
   }

   double posVol = PositionGetDouble(POSITION_VOLUME);
   double closeVol = (volume > 0) ? volume : posVol;
   closeVol = NormalizeDouble(closeVol, 2);

   if(closeVol <= 0)
   {
      Log("WARNING: Volume to close is 0");
      return false;
   }

   ENUM_ORDER_TYPE closeType;
   double closePrice;

   if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
   {
      closeType  = ORDER_TYPE_SELL;
      closePrice = GetBid();
   }
   else
   {
      closeType  = ORDER_TYPE_BUY;
      closePrice = GetAsk();
   }

   if(!trade.PositionClosePartial(g_ticket, closeVol, closePrice))
   {
      Log(StringFormat("ERROR: Close failed — %s", trade.ResultComment()));
      return false;
   }

   g_currentVolume = NormalizeDouble(g_currentVolume - closeVol, 2);
   Log(StringFormat("CLOSED %.2f lots @ %.5f  Remaining: %.2f",
       closeVol, trade.ResultPrice(), g_currentVolume));
   return true;
}

//+------------------------------------------------------------------+
//| MODIFY SL                                                         |
//+------------------------------------------------------------------+
bool ModifySL(double newSL)
{
   if(g_ticket == 0) return false;

   if(!PositionSelectByTicket(g_ticket))
      return false;

   double currentTP = PositionGetDouble(POSITION_TP);

   if(!trade.PositionModify(g_ticket, newSL, currentTP))
   {
      Log(StringFormat("ERROR: SL modify failed — %s", trade.ResultComment()));
      return false;
   }

   g_slPrice = newSL;
   Log(StringFormat("SL MOVED to %.5f", newSL));
   return true;
}

//+------------------------------------------------------------------+
//| MANAGE TRADE                                                      |
//+------------------------------------------------------------------+
void ManageTrade()
{
   if(g_state != STATE_HALF_OPEN && g_state != STATE_TRAIL)
      return;

   if(g_ticket == 0) return;

   double bid = GetBid();
   double ask = GetAsk();
   g_tickCount++;

   // --- Check TP1: close 50%, move SL to break-even ---
   if(!g_tp1Hit)
   {
      if(g_tradeLong && ask >= g_tp1Price)
      {
         g_tp1Hit = true;
         Log(StringFormat("TP1 HIT @ %.5f", ask));
         double halfVol = NormalizeDouble(g_initialVolume / 2, 2);
         if(ClosePosition(halfVol))
         {
            ModifySL(g_entryPrice);
            g_state = STATE_TRAIL;
            Log("SL moved to break-even (entry price)");
         }
      }
      else if(!g_tradeLong && bid <= g_tp1Price)
      {
         g_tp1Hit = true;
         Log(StringFormat("TP1 HIT @ %.5f", bid));
         double halfVol = NormalizeDouble(g_initialVolume / 2, 2);
         if(ClosePosition(halfVol))
         {
            ModifySL(g_entryPrice);
            g_state = STATE_TRAIL;
            Log("SL moved to break-even (entry price)");
         }
      }
   }

   // --- Check TP2: close remaining ---
   if(g_tp1Hit && !g_tp2Hit)
   {
      if(g_tradeLong && ask >= g_tp2Price)
      {
         g_tp2Hit = true;
         Log(StringFormat("TP2 HIT @ %.5f", ask));
         ClosePosition();
         g_dayDone = true;
         g_state   = STATE_DONE;
         Log("ALL POSITIONS CLOSED — Day done");
      }
      else if(!g_tradeLong && bid <= g_tp2Price)
      {
         g_tp2Hit = true;
         Log(StringFormat("TP2 HIT @ %.5f", bid));
         ClosePosition();
         g_dayDone = true;
         g_state   = STATE_DONE;
         Log("ALL POSITIONS CLOSED — Day done");
      }
   }

   // --- Check SL ---
   if(g_tradeLong && bid <= g_slPrice)
   {
      Log(StringFormat("SL HIT @ %.5f", bid));
      ClosePosition();
      g_dayDone = true;
      g_state   = STATE_DONE;
      Log("STOPPED OUT — Day done");
   }
   else if(!g_tradeLong && ask >= g_slPrice)
   {
      Log(StringFormat("SL HIT @ %.5f", ask));
      ClosePosition();
      g_dayDone = true;
      g_state   = STATE_DONE;
      Log("STOPPED OUT — Day done");
   }
}

//+------------------------------------------------------------------+
//| FORCE CLOSE AT 11:30                                              |
//+------------------------------------------------------------------+
void CheckForceClose()
{
   MqlDateTime ny = GetTimeComponents(GetNYTime());
   int tMin = ny.hour * 60 + ny.min;
   int endMin = InpTradeEndH * 60 + InpTradeEndM;

   if(tMin >= endMin && (g_state == STATE_HALF_OPEN || g_state == STATE_TRAIL))
   {
      Log("11:30 NY — FORCE CLOSE");
      ClosePosition();
      g_dayDone = true;
      g_state   = STATE_DONE;
      Log("Day done — force closed");
   }
}

//+------------------------------------------------------------------+
//| EMERGENCY STOP                                                    |
//+------------------------------------------------------------------+
void EmergencyStop()
{
   Log("EMERGENCY STOP — Closing all positions...");

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)  continue;

      ENUM_ORDER_TYPE closeType;
      double closePrice;

      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
      {
         closeType  = ORDER_TYPE_SELL;
         closePrice = GetBid();
      }
      else
      {
         closeType  = ORDER_TYPE_BUY;
         closePrice = GetAsk();
      }

      double vol = PositionGetDouble(POSITION_VOLUME);

      if(trade.PositionClose(ticket, closePrice))
         Log(StringFormat("Emergency closed %.2f lots @ %.5f", vol, trade.ResultPrice()));
      else
         Log(StringFormat("Emergency close FAILED for ticket %I64u", ticket));
   }
}

//+------------------------------------------------------------------+
//| PRINT STATUS                                                      |
//+------------------------------------------------------------------+
void PrintStatus()
{
   MqlDateTime ny = GetTimeComponents(GetNYTime());
   double bid = GetBid();
   double ask = GetAsk();

   string stateStr;
   switch(g_state)
   {
      case STATE_IDLE:       stateStr = "IDLE — waiting for range window"; break;
      case STATE_BUILDING:   stateStr = "BUILDING — collecting ORB range"; break;
      case STATE_WAIT_BREAK: stateStr = "WAITING — range locked, watching for breakout"; break;
      case STATE_HALF_OPEN:  stateStr = "ACTIVE — TP1 pending (close 50% + move SL)"; break;
      case STATE_TRAIL:      stateStr = "TRAILING — TP1 hit, SL at break-even, TP2 pending"; break;
      case STATE_DONE:       stateStr = "DONE — day finished"; break;
      default:               stateStr = "UNKNOWN"; break;
   }

   Print("============================================================");
   PrintFormat("  %s  |  %04d-%02d-%02d %02d:%02d:%02d NY",
               _Symbol, ny.year, ny.mon, ny.day, ny.hour, ny.min, ny.sec);
   PrintFormat("  State: %s", stateStr);
   PrintFormat("  Bid: %.5f  Ask: %.5f", bid, ask);

   if(g_orbHigh > 0 && g_orbLow > 0)
      PrintFormat("  ORB: %.5f / %.5f", g_orbHigh, g_orbLow);
   else
      Print("  ORB: Building...");

   if(g_state == STATE_HALF_OPEN || g_state == STATE_TRAIL)
   {
      string dir = g_tradeLong ? "LONG" : "SHORT";
      PrintFormat("  Position: %s  Entry: %.5f", dir, g_entryPrice);
      PrintFormat("  Volume: %.2f / %.2f", g_currentVolume, g_initialVolume);
      PrintFormat("  TP1: %.5f (%s)", g_tp1Price, g_tp1Hit ? "HIT" : "pending");
      PrintFormat("  TP2: %.5f (%s)", g_tp2Price, g_tp2Hit ? "HIT" : "pending");
      PrintFormat("  SL:  %.5f", g_slPrice);
   }
   Print("============================================================");
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Check for new day
   CheckNewDay();

   // Force close at 11:30
   CheckForceClose();

   // Check if new M1 bar arrived
   if(IsNewM1Bar())
   {
      // Get the bar that just closed
      MqlRates rates[1];
      if(CopyRates(_Symbol, PERIOD_M1, 1, 1, rates) == 1)
      {
         MqlDateTime barTime;
         TimeToStruct(rates[0].time, barTime);

         // Update ORB range
         UpdateORBRange(rates[0].high, rates[0].low, barTime);

         // Check breakout on new bar
         CheckBreakout();
      }
   }

   // Manage active trade on every tick
   ManageTrade();
}

//+------------------------------------------------------------------+
//| OnTimer — status display every 5 seconds                         |
//+------------------------------------------------------------------+
void OnTimer()
{
   PrintStatus();
}

//+------------------------------------------------------------------+
//| ChartEvent — Ctrl+C equivalent via chart button                  |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id == CHARTEVENT_KEYDOWN && lparam == 27) // ESC key
   {
      Print("\nESC detected — emergency stop...");
      EmergencyStop();
      PrintStatus();
   }
}
