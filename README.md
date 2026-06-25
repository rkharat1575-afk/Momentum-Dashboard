# Sharekhan Nifty Momentum Dashboard & Trading Engine

An advanced real-time options microstructure trading system for Nifty Index, featuring an institutional order flow imbalance (OFI) radar, option chain volume velocity analytics, automated trade signal generation, and Telegram notifications.

## Project Architecture

The system is split into two main components:
1. **React Frontend Dashboard** (located in `NIFTY MOMENTUM DASHBOARD FROM AI`): A lightning-fast, single-screen light-themed dashboard showing real-time market microstructure, strike recommendations, active trade status, and order flow indicators. Can be deployed to **Vercel** or run locally.
2. **Stateful Python Backend** (located in the root directory): A persistent suite of scripts that download scrip tokens daily, stream tick data via Sharekhan API WebSockets, perform option chain math, compute signal velocities, and broadcast events to the frontend via a local WebSocket port (`8080`). Must run on a persistent machine (local PC or persistent VPS).

---

## Installation & Setup

### 1. Backend Prerequisites (Python)

Ensure Python 3.9+ is installed. Install the required dependencies:
```bash
pip install shareconnect websocket-client streamlit pandas plotly requests pycryptodome cryptography six python-dotenv
```

### 2. Frontend Prerequisites (Node.js)

Ensure Node.js 18+ is installed. Navigate to the frontend directory and install dependencies:
```bash
cd "NIFTY MOMENTUM DASHBOARD FROM AI"
npm install
```

---

## Configuration & Environment Variables

Copy the `.env.example` file to `.env` in the root directory and fill in your credentials:
```bash
cp .env.example .env
```

Your `.env` file should contain:
```env
# Sharekhan API Credentials
SHAREKHAN_API_KEY=your_sharekhan_api_key_here
SHAREKHAN_SECRET_KEY=your_sharekhan_secret_key_here

# Telegram Alerts Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

*Note: `.env` is listed in `.gitignore` and will never be committed to Git.*

---

## Running the System Locally

To start the system, run the sequence of scripts to fetch fresh tokens, optimize parameters, start the WebSocket backend, and launch the React dashboard.

### Option A: Fully Automated Startup (Windows)
Run the startup batch file:
```bash
START_MOMENTUM_ENGINE.bat
```

### Option B: Step-by-Step Manual Startup

1. **Daily Login** (Run once every morning before 9:15 AM to generate a fresh `access_token.txt`):
   ```bash
   python daily_login_v2.py
   ```
   *Follow the terminal instructions to paste your browser redirection token.*

2. **Select Option Tokens**:
   ```bash
   python auto_tokens.py
   ```

3. **Optimize ML Weights**:
   ```bash
   python auto_optimizer.py
   ```

4. **Launch the WebSocket Backend**:
   ```bash
   python dashboard_backend.py
   ```
   *Starts the local server on `ws://localhost:8080`.*

5. **Launch the Frontend Dashboard**:
   ```bash
   cd "NIFTY MOMENTUM DASHBOARD FROM AI"
   npm run dev
   ```
   *Opens the browser to the local React dashboard page.*

---

## Running the Streamlit Dashboard

If you prefer using the older Streamlit-based terminal:
1. Complete the login step (`python daily_login_v2.py`).
2. Run the setup: `python auto_setup.py`.
3. Start the live tick feeder in one window: `python tick_live.py`.
4. Run the Streamlit app:
   ```bash
   streamlit run sharekhan_terminal_v4.py
   ```

---

## Deployment to Vercel (One-Click Setup)

The frontend is designed to be deployed to **Vercel** with one click.

### Steps to Deploy:
1. Push this project to your GitHub repository:
   `https://github.com/rkharat1575-afk/Momentum-Dashboard`
2. Log in to Vercel and click **Add New** -> **Project**.
3. Import your `Momentum-Dashboard` repository.
4. **Important Project Settings**:
   - **Root Directory**: Set this to `NIFTY MOMENTUM DASHBOARD FROM AI`.
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
   - **Install Command**: `npm install`
5. **Environment Variables** (Optional):
   - Add `VITE_WS_URL` if your Python backend is hosted on a remote server (e.g. `wss://your-backend-vps.com`).
   - If left blank, the frontend runs in the client browser and attempts to connect to `ws://localhost:8080` (your local running Python backend).
6. Click **Deploy**. Vercel will build the frontend and serve it at a public `.vercel.app` URL.
