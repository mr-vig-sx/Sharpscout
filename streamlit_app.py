import streamlit as st
import requests
import json
import os
import pandas as pd
import re
from datetime import datetime

# Page config
st.set_page_config(
    page_title="SharpScout - Polymarket Trade Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark theme
st.markdown("""
<style>
    .main {
        background-color: #0a0e27;
    }
    .stApp {
        background-color: #0a0e27;
        color: #e0e0e0;
    }
    h1 {
        color: #00d4ff;
    }
    h2, h3 {
        color: #00d4ff;
    }
    .stButton>button {
        background-color: #00d4ff;
        color: #0a0e27;
        border: none;
        border-radius: 6px;
        font-weight: 600;
    }
    .stButton>button:hover {
        background-color: #00b8e6;
    }
    .wallet-badge {
        background-color: #1e2442;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 11px;
        color: #00d4ff;
        font-family: 'Courier New', monospace;
    }
    .highlight-2 {
        background-color: rgba(255, 193, 7, 0.2) !important;
        border-left: 3px solid #ffc107;
    }
    .highlight-3 {
        background-color: rgba(76, 175, 80, 0.2) !important;
        border-left: 3px solid #4caf50;
    }
</style>
""", unsafe_allow_html=True)

# Hardcoded wallet addresses to track
HARDCODED_WALLETS = [
    {'address': '0x16b29c50f2439faf627209b2ac0c7bbddaa8a881', 'label': 'Freedom'},
    #{'address': '0xee613b3fc183ee44f9da9c05f53e2da107e3debf', 'label': 'Quantbet'},#
    {'address': '0x91654fd592ea5339fc0b1b2f2b30bfffa5e75b98', 'label': 'ST'},
    {'address': '0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee', 'label': 'Kyle/Ray'},
    {'address': '0x14964aefa2cd7caff7878b3820a690a03c5aa429', 'label': 'GMPM'},
    {'address': '0x2c57db9e442ef5ffb2651f03afd551171738c94d', 'label': 'ZeroOptimist'},
    {'address': '0x9f138019d5481fdc5c59b93b0ae4b9b817cce0fd', 'label': 'Bienville'},
    # Add more wallets here as needed
    # {'address': '0x...', 'label': 'WalletName'},
]

# File to store wallet addresses (for additional wallets added via UI)
DATA_DIR = os.path.expanduser('~/.sharpscout')
WALLETS_FILE = os.path.join(DATA_DIR, 'wallets.json')

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize session state with hardcoded wallets
if 'wallets' not in st.session_state:
    # Start with hardcoded wallets
    st.session_state.wallets = HARDCODED_WALLETS.copy()
    
    # Also load any additional wallets from file
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            wallets_data = json.load(f)
            # Convert old format (list of strings) to new format (list of dicts)
            if wallets_data and isinstance(wallets_data[0], str):
                file_wallets = [{'address': addr, 'label': ''} for addr in wallets_data]
            else:
                file_wallets = wallets_data
            
            # Add file wallets that aren't already in hardcoded list
            hardcoded_addresses = {w['address'].lower() for w in HARDCODED_WALLETS}
            for wallet in file_wallets:
                if wallet.get('address', '').lower() not in hardcoded_addresses:
                    st.session_state.wallets.append(wallet)

if 'market_cache' not in st.session_state:
    st.session_state.market_cache = {}

def load_wallets():
    """Load wallet addresses - combines hardcoded and file wallets"""
    wallets = HARDCODED_WALLETS.copy()
    
    # Add wallets from file that aren't already in hardcoded list
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            file_wallets_data = json.load(f)
            # Convert old format (list of strings) to new format (list of dicts)
            if file_wallets_data and isinstance(file_wallets_data[0], str):
                file_wallets = [{'address': addr, 'label': ''} for addr in file_wallets_data]
            else:
                file_wallets = file_wallets_data
            
            # Add file wallets that aren't already in hardcoded list
            hardcoded_addresses = {w['address'].lower() for w in HARDCODED_WALLETS}
            for wallet in file_wallets:
                if wallet.get('address', '').lower() not in hardcoded_addresses:
                    wallets.append(wallet)
    
    return wallets

def save_wallets(wallets):
    """Save wallet addresses to file"""
    with open(WALLETS_FILE, 'w') as f:
        json.dump(wallets, f, indent=2)
    st.session_state.wallets = wallets

@st.cache_data(ttl=60)  # Cache for 1 minute (short to catch resolved markets quickly)
def fetch_market_info_cached(condition_id):
    """Fetch market name, event date, current prices, and resolved status from Polymarket API (cached)"""
    if not condition_id:
        return {'name': 'Unknown Market', 'date': None, 'prices': {}, 'resolved': False}
    
    market_name = None
    event_date = None
    outcome_prices = {}
    is_resolved = False
    
    # Try CLOB API first (most reliable for closed/resolved status)
    try:
        url = f"https://clob.polymarket.com/markets/{condition_id}"
        response = requests.get(url, params={}, timeout=3)
        if response.status_code == 200:
            market = response.json()
            market_name = market.get('question') or market.get('title')
            event_date = market.get('end_date_iso') or market.get('game_start_time')
            
            # Check closed status - this is the key field!
            is_resolved = market.get('closed', False) is True
            if not is_resolved:
                is_resolved = market.get('archived', False) is True
            if not is_resolved:
                is_resolved = market.get('accepting_orders', True) is False
            
            # Get outcome prices from tokens
            if 'tokens' in market:
                for token in market['tokens']:
                    outcome_name = token.get('outcome') or token.get('title')
                    price = token.get('price')
                    if outcome_name is not None and price is not None:
                        try:
                            outcome_prices[outcome_name] = float(price)
                            # Also check if price indicates resolution
                            if float(price) <= 0.05 or float(price) >= 0.95:
                                is_resolved = True
                        except (ValueError, TypeError):
                            pass
            
            # Return if we got data
            if market_name or outcome_prices:
                return {'name': market_name, 'date': event_date, 'prices': outcome_prices, 'resolved': is_resolved}
    except Exception:
        pass
    
    # Try markets endpoint as fallback
    try:
        url = "https://data-api.polymarket.com/markets"
        params = {'conditionId': condition_id}
        response = requests.get(url, params=params, timeout=3)
        if response.status_code == 200:
            data = response.json()
            markets = data if isinstance(data, list) else (data.get('data', []) if isinstance(data, dict) else [])
            if markets and len(markets) > 0:
                market = markets[0]
                if not market_name:
                    market_name = market.get('question') or market.get('title') or market.get('slug')
                if not event_date:
                    event_date = market.get('endDate') or market.get('startDate') or market.get('date')
                
                # Check resolved status
                if not is_resolved:
                    is_resolved = market.get('resolved', False) is True
                if not is_resolved:
                    is_resolved = market.get('active', True) is False
                
                # Get outcome prices from tokens
                if 'tokens' in market and not outcome_prices:
                    for token in market['tokens']:
                        outcome_name = token.get('outcome') or token.get('title') or token.get('name')
                        price = token.get('price') or token.get('lastPrice') or token.get('currentPrice') or token.get('lastPriceUsd')
                        if outcome_name and price is not None:
                            try:
                                outcome_prices[outcome_name] = float(price)
                                if float(price) <= 0.05 or float(price) >= 0.95:
                                    is_resolved = True
                            except (ValueError, TypeError):
                                pass
    except Exception:
        pass
    
    # Fallback to events endpoint
    try:
        url = "https://data-api.polymarket.com/events"
        params = {'conditionId': condition_id}
        response = requests.get(url, params=params, timeout=3)
        if response.status_code == 200:
            data = response.json()
            event_data = None
            if isinstance(data, list) and len(data) > 0:
                event_data = data[0]
            elif isinstance(data, dict):
                if 'data' in data and isinstance(data['data'], list) and len(data['data']) > 0:
                    event_data = data['data'][0]
                else:
                    event_data = data
            
            if event_data:
                if not market_name:
                    market_name = event_data.get('title') or event_data.get('question') or event_data.get('slug')
                if not event_date:
                    event_date = event_data.get('endDate') or event_data.get('startDate') or event_data.get('date') or event_data.get('eventDate')
                
                # Check resolved status
                if not is_resolved:
                    is_resolved = event_data.get('resolved', False) is True
                
                # Get outcome prices if available
                if 'outcomes' in event_data:
                    for outcome in event_data['outcomes']:
                        outcome_name = outcome.get('title') or outcome.get('name')
                        price = outcome.get('price') or outcome.get('lastPrice') or outcome.get('currentPrice')
                        if outcome_name and price is not None:
                            try:
                                outcome_prices[outcome_name] = float(price)
                            except (ValueError, TypeError):
                                pass
    except Exception:
        pass
    
    # Fallback to shortened condition_id
    if not market_name:
        short_id = condition_id[:16] + '...' if len(condition_id) > 16 else condition_id
        market_name = short_id
    
    return {'name': market_name, 'date': event_date, 'prices': outcome_prices, 'resolved': is_resolved}

def fetch_market_info(condition_id):
    """Fetch market info with session cache layer"""
    cache_key = f"{condition_id}_info"
    if cache_key in st.session_state.market_cache:
        return st.session_state.market_cache[cache_key]
    
    result = fetch_market_info_cached(condition_id)
    st.session_state.market_cache[cache_key] = result
    return result

def is_market_resolved(market_info, outcome_name):
    """Check if market is resolved based on outcome price"""
    prices = market_info.get('prices', {})
    if not prices:
        return False  # Can't determine, so show it
    
    # Check if this specific outcome price indicates resolution
    price = prices.get(outcome_name)
    if price is None:
        # Check all prices - if any outcome is < 0.01 or > 0.99, market is resolved
        for outcome, outcome_price in prices.items():
            if outcome_price < 0.01 or outcome_price > 0.99:
                return True
        return False
    
    # If this outcome's price is < 0.01 or > 0.99, it's resolved
    return price < 0.01 or price > 0.99

def fetch_market_name(condition_id):
    """Fetch market name (backward compatibility)"""
    info = fetch_market_info(condition_id)
    return info['name']

@st.cache_data(ttl=300)  # Cache trades for 5 minutes
def fetch_polymarket_trades_cached(wallet_address):
    """Fetch trades from Polymarket API (cached)"""
    try:
        url = "https://data-api.polymarket.com/trades"
        params = {
            'user': wallet_address,
            'limit': 100
        }
        response = requests.get(url, params=params, timeout=8)  # Reduced timeout
        response.raise_for_status()
        data = response.json()
        
        trades = []
        if isinstance(data, list):
            trades = data
        elif isinstance(data, dict) and 'data' in data:
            trades = data['data']
        elif isinstance(data, dict) and 'trades' in data:
            trades = data['trades']
        
        return trades
    except Exception as e:
        return []

def extract_date_from_event_slug(event_slug):
    """Extract date from eventSlug (e.g., 'nhl-nj-ott-2025-12-10' -> '2025-12-10')"""
    if not event_slug:
        return None
    try:
        # Event slug format: sport-team1-team2-YYYY-MM-DD or similar
        # Look for YYYY-MM-DD pattern
        import re
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', event_slug)
        if date_match:
            return date_match.group(1)
    except Exception:
        pass
    return None

def fetch_polymarket_trades(wallet_address):
    """Fetch trades and filter by today or future dates from eventSlug"""
    trades = fetch_polymarket_trades_cached(wallet_address)
    
    if not trades:
        return []
    
    # Get today's date in YYYY-MM-DD format
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.now().date()
    
    # Filter trades to only include today's or future games using eventSlug
    active_trades = []
    for trade in trades:
        event_slug = trade.get('eventSlug') or trade.get('eventSlug')
        if event_slug:
            event_date_str = extract_date_from_event_slug(event_slug)
            if event_date_str:
                try:
                    event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                    # Only include if event date is today or in the future
                    if event_date >= today_date:
                        active_trades.append(trade)
                except Exception:
                    # If date parsing fails, exclude it (safer)
                    pass
        else:
            # If no eventSlug, exclude it (safer - we can't verify the date)
            pass
    
    # Use title directly from trades response (already available!)
    for trade in active_trades:
        condition_id = trade.get('conditionId') or trade.get('condition_id') or trade.get('market')
        market_name = trade.get('title') or trade.get('marketName') or trade.get('market_name') or 'Unknown Market'
        event_slug = trade.get('eventSlug', '')
        
        trade['condition_id'] = condition_id
        trade['market_name'] = market_name
        trade['market_date'] = extract_date_from_event_slug(event_slug)  # Extract date from slug
    
    return active_trades

def aggregate_position(trades):
    """Aggregate trades into a single position with improved position recognition"""
    if not trades:
        return None
    
    total_shares = 0
    total_cost = 0
    outcomes = set()
    buy_trades = []
    sell_trades = []
    
    for trade in trades:
        # Use 'size' field directly from API (more reliable)
        amount = float(trade.get('size', 0) or trade.get('amount', 0) or trade.get('quantity', 0) or 0)
        if amount == 0:
            continue
            
        # Use 'price' field directly from API
        price = float(trade.get('price', 0) or trade.get('priceNum', 0) or trade.get('fillPrice', 0) or 0)
        if price == 0:
            continue
        
        # Use 'side' field directly from API - it's explicitly "BUY" or "SELL"
        side = (trade.get('side', '') or '').upper()
        outcome = trade.get('outcome') or trade.get('outcomeName') or trade.get('outcomeTitle') or 'Unknown'
        outcomes.add(outcome)
        
        # Determine buy/sell from explicit side field
        is_buy = side == 'BUY'
        
        # Track trades separately for better analysis
        if is_buy:
            buy_trades.append({'amount': amount, 'price': price})
            total_shares += amount
            total_cost += amount * price
        else:
            sell_trades.append({'amount': amount, 'price': price})
            total_shares -= amount
            total_cost -= amount * price  # Selling reduces cost basis
    
    # Only return position if there are net shares
    if abs(total_shares) < 0.0001:
        return None
    
    # Calculate weighted average cost
    avg_cost = total_cost / total_shares if total_shares != 0 else 0
    
    # Get most common outcome or combine if multiple
    if len(outcomes) == 1:
        outcome_str = list(outcomes)[0]
    elif len(outcomes) > 1:
        outcome_str = ', '.join(sorted(outcomes))
    else:
        outcome_str = 'Unknown'
    
    return {
        'outcome': outcome_str,
        'total_shares': abs(total_shares),
        'avg_cost_per_share': avg_cost,
        'total_cost': abs(total_cost),
        'position_type': 'Long' if total_shares > 0 else 'Short',
        'trade_count': len(trades),
        'buy_count': len(buy_trades),
        'sell_count': len(sell_trades)
    }

def get_all_positions():
    """Fetch and aggregate positions from all wallets with progress indicator"""
    # Always use hardcoded wallets + any from session state
    wallets = st.session_state.wallets if st.session_state.wallets else load_wallets()
    if not wallets:
        return []
    
    # Show progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_wallets = len(wallets)
    markets_dict = {}
    
    # Fetch trades for each wallet with progress
    all_trades_by_wallet = {}
    for idx, wallet_obj in enumerate(wallets):
        if isinstance(wallet_obj, dict):
            wallet_address = wallet_obj['address']
            wallet_label = wallet_obj.get('label', wallet_address[:10])
        else:
            wallet_address = wallet_obj
            wallet_label = wallet_address[:10]
        
        status_text.text(f"Fetching trades for {wallet_label}... ({idx+1}/{total_wallets})")
        progress_bar.progress((idx + 0.2) / total_wallets)
        
        trades = fetch_polymarket_trades(wallet_address)
        all_trades_by_wallet[wallet_label] = {
            'address': wallet_address,
            'trades': trades
        }
    
    # Collect all unique condition IDs for price checking
    status_text.text("Checking market prices...")
    progress_bar.progress(0.5)
    
    all_condition_ids = set()
    for wallet_label, wallet_data in all_trades_by_wallet.items():
        trades = wallet_data['trades']
        for trade in trades:
            condition_id = trade.get('condition_id') or trade.get('conditionId')
            if condition_id:
                all_condition_ids.add(condition_id)
    
    # Batch check prices for resolved markets (price <= 5c or >= 95c)
    resolved_condition_ids = set()
    market_info_cache = {}
    
    for condition_id in all_condition_ids:
        market_info = fetch_market_info(condition_id)
        market_info_cache[condition_id] = market_info
        
        # Check if market is resolved
        is_resolved = False
        
        # First check explicit resolved status
        if market_info.get('resolved', False) is True:
            is_resolved = True
        
        # Then check prices - if ANY outcome price is <= 5c or >= 95c, market is resolved
        prices = market_info.get('prices', {})
        if prices:
            for outcome_name, price in prices.items():
                try:
                    price_float = float(price)
                    if price_float <= 0.05 or price_float >= 0.95:
                        is_resolved = True
                        break
                except (ValueError, TypeError):
                    continue
        
        # If still not resolved and no prices, try CLOB API as fallback (most reliable)
        if not is_resolved and not prices:
            try:
                url = f"https://clob.polymarket.com/markets/{condition_id}"
                response = requests.get(url, timeout=2)
                if response.status_code == 200:
                    market = response.json()
                    # Check closed status - this is the definitive field
                    if market.get('closed') is True:
                        is_resolved = True
                    elif market.get('archived') is True:
                        is_resolved = True
                    elif market.get('accepting_orders') is False:
                        is_resolved = True
                    # Also check token prices
                    if 'tokens' in market:
                        for token in market['tokens']:
                            price = token.get('price')
                            if price is not None:
                                try:
                                    price_float = float(price)
                                    if price_float <= 0.05 or price_float >= 0.95:
                                        is_resolved = True
                                        break
                                except (ValueError, TypeError):
                                    continue
            except Exception:
                pass
        
        if is_resolved:
            resolved_condition_ids.add(condition_id)
    
    # Now process only active markets (already filtered by date via eventSlug, now filter by price)
    status_text.text("Processing active positions...")
    progress_bar.progress(0.7)
    
    for wallet_label, wallet_data in all_trades_by_wallet.items():
        wallet_address = wallet_data['address']
        trades = wallet_data['trades']
        
        # Filter out trades from resolved markets
        active_trades = [
            trade for trade in trades
            if (trade.get('condition_id') or trade.get('conditionId') or trade.get('market')) not in resolved_condition_ids
        ]
        
        if not active_trades:
            continue
        
        # Group trades by market and outcome
        market_outcome_trades = {}
        for trade in active_trades:
            market_name = trade.get('market_name') or trade.get('market') or trade.get('conditionId') or trade.get('condition_id') or 'Unknown Market'
            condition_id = trade.get('condition_id') or trade.get('conditionId') or trade.get('market')
            outcome = trade.get('outcome') or trade.get('outcomeName', 'Unknown')
            market_date = trade.get('market_date')
            
            if market_name not in market_outcome_trades:
                market_outcome_trades[market_name] = {'date': market_date, 'outcomes': {}, 'condition_id': condition_id}
            
            if outcome not in market_outcome_trades[market_name]['outcomes']:
                market_outcome_trades[market_name]['outcomes'][outcome] = []
            
            trade['wallet_address'] = wallet_address
            trade['wallet_label'] = wallet_label
            trade['condition_id'] = condition_id
            market_outcome_trades[market_name]['outcomes'][outcome].append(trade)
        
        # Aggregate positions for each market
        for market_name, market_data in market_outcome_trades.items():
            if market_name not in markets_dict:
                condition_id = market_data.get('condition_id')
                markets_dict[market_name] = {
                    'date': market_data.get('date'),
                    'wallets': {},
                    'market_info': market_info_cache.get(condition_id) if condition_id else None,
                    'condition_id': condition_id
                }
            
            outcome_positions = {}
            for outcome, trades_list in market_data['outcomes'].items():
                position = aggregate_position(trades_list)
                if position:
                    outcome_positions[outcome] = position
            
            if outcome_positions:
                best_outcome = max(outcome_positions.items(), key=lambda x: x[1]['total_cost'])
                markets_dict[market_name]['wallets'][wallet_label] = best_outcome[1]
    
    # Convert to list format (markets_dict already contains only active markets)
    status_text.text("Finalizing positions...")
    progress_bar.progress(0.9)
    
    markets_list = []
    
    for market_name, market_data in markets_dict.items():
        wallet_positions = market_data.get('wallets', {})
        market_date_str = market_data.get('date')
        
        # All markets in markets_dict are already active (filtered above)
        if wallet_positions:
            markets_list.append({
                'market_name': market_name,
                'market_date': market_date_str,
                'wallets': wallet_positions,
                'wallet_count': len(wallet_positions)
            })
    
    # Calculate total wager and sort by total $ wagered (descending)
    for market in markets_list:
        total_wager = sum(pos['total_cost'] for pos in market['wallets'].values())
        market['total_wager'] = total_wager
    
    markets_list.sort(key=lambda x: -x['total_wager'])
    
    progress_bar.progress(1.0)
    status_text.empty()
    progress_bar.empty()
    
    return markets_list

# Removed cached version - now using direct function with progress indicators

# Main app
st.title("📊 SharpScout")
st.markdown("**Polymarket Trade Scouting Dashboard**")

# Sidebar for wallet management
with st.sidebar:
    st.header("Wallet Management")
    
    # Wallets are already loaded in session state initialization above
    
    # Add wallet form
    with st.form("add_wallet_form"):
        st.subheader("Add Wallet")
        wallet_label = st.text_input("Label (e.g., Freedom)", key="wallet_label")
        wallet_address = st.text_input("Wallet Address (0x...)", key="wallet_address", max_chars=42)
        submitted = st.form_submit_button("Add Wallet")
        
        if submitted:
            if not wallet_address:
                st.error("Please enter a wallet address")
            elif not wallet_address.startswith('0x') or len(wallet_address) != 42:
                st.error("Invalid wallet address format. Must start with 0x and be 42 characters long.")
            else:
                wallets = st.session_state.wallets.copy()
                if wallet_address.lower() not in [w.get('address', w).lower() if isinstance(w, dict) else w.lower() for w in wallets]:
                    wallets.append({'address': wallet_address, 'label': wallet_label})
                    save_wallets(wallets)
                    st.success(f"Wallet added: {wallet_label or wallet_address[:10]}")
                    st.rerun()
                else:
                    st.error("Wallet address already exists")
    
    # Display current wallets
    st.subheader("Current Wallets")
    if st.session_state.wallets:
        for wallet in st.session_state.wallets:
            wallet_addr = wallet.get('address', wallet) if isinstance(wallet, dict) else wallet
            wallet_lbl = wallet.get('label', '') if isinstance(wallet, dict) else ''
            display_text = f"{wallet_lbl}: {wallet_addr[:10]}..." if wallet_lbl else f"{wallet_addr[:10]}..."
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(display_text)
            with col2:
                if st.button("×", key=f"remove_{wallet_addr}"):
                    wallets = [w for w in st.session_state.wallets if (w.get('address', w) if isinstance(w, dict) else w).lower() != wallet_addr.lower()]
                    save_wallets(wallets)
                    st.rerun()
    else:
        st.info("No wallets added yet")
    
    # Backup button
    st.divider()
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            st.download_button(
                label="📥 Backup Wallets",
                data=f.read(),
                file_name=f"wallets_backup_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )

# Main content area
if not st.session_state.wallets:
    st.info("👈 Add wallet addresses in the sidebar to start scouting trades")
else:
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Refresh Positions", use_container_width=True):
            # Clear all caches
            if 'market_cache' in st.session_state:
                st.session_state.market_cache.clear()
            # Clear Streamlit cache
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        # Export CSV
        positions = get_all_positions()
        if positions:
            # Prepare CSV data
            csv_rows = []
            for market in positions:
                for wallet_label, position in market['wallets'].items():
                    csv_rows.append({
                        'Market Name': market['market_name'],
                        'Wallet Label': wallet_label,
                        'Outcome': position['outcome'],
                        'Total Shares': position['total_shares'],
                        'Avg Cost Per Share': position['avg_cost_per_share'],
                        'Total Cost': position['total_cost'],
                        'Trade Count': position['trade_count']
                    })
            
            if csv_rows:
                df = pd.DataFrame(csv_rows)
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📊 Export CSV",
                    data=csv,
                    file_name=f"polymarket_positions_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
    
    # Display positions
    st.divider()
    st.subheader("Positions by Market")
    
    positions = get_all_positions()
    
    if not positions:
        st.info("No positions found. Make sure wallets have trades and click Refresh Positions.")
    else:
        # Positions are already sorted by total_wager (descending) in get_all_positions
        # Get all wallet labels
        all_wallet_labels = set()
        for market in positions:
            all_wallet_labels.update(market['wallets'].keys())
        sorted_wallet_labels = sorted(all_wallet_labels)
        total_wallets = len(sorted_wallet_labels)
        
        # Create table data
        table_data = []
        for market in positions:
            row = {'Market Name': market['market_name']}
            
            # Determine highlight
            wallet_count = market['wallet_count']
            highlight_class = ''
            if total_wallets >= 3:
                if wallet_count >= 3:
                    highlight_class = 'highlight-3'
                elif wallet_count >= 2:
                    highlight_class = 'highlight-2'
            elif total_wallets >= 2 and wallet_count >= 2:
                highlight_class = 'highlight-2'
            
            # Add wallet columns
            for wallet_label in sorted_wallet_labels:
                position = market['wallets'].get(wallet_label)
                if position:
                    row[wallet_label] = (
                        f"{position['outcome']}\n"
                        f"Shares: {position['total_shares']:.4f}\n"
                        f"Avg Cost: ${position['avg_cost_per_share']:.4f}\n"
                        f"Total Cost: ${position['total_cost']:.4f}\n"
                        f"({position['trade_count']} trades)"
                    )
                else:
                    row[wallet_label] = "-"
            
            table_data.append(row)
        
        if table_data:
            # Display as a more readable format
            for market in positions:
                wallet_count = market['wallet_count']
                
                # Determine highlight style
                highlight_style = ""
                if total_wallets >= 3:
                    if wallet_count >= 3:
                        highlight_style = "background-color: rgba(76, 175, 80, 0.2); border-left: 3px solid #4caf50; padding: 10px;"
                    elif wallet_count >= 2:
                        highlight_style = "background-color: rgba(255, 193, 7, 0.2); border-left: 3px solid #ffc107; padding: 10px;"
                
                with st.container():
                    if highlight_style:
                        st.markdown(f'<div style="{highlight_style}">', unsafe_allow_html=True)
                    
                    st.markdown(f"### {market['market_name']}")
                    
                    cols = st.columns(len(sorted_wallet_labels))
                    for idx, wallet_label in enumerate(sorted_wallet_labels):
                        with cols[idx]:
                            position = market['wallets'].get(wallet_label)
                            if position:
                                st.markdown(f"**{wallet_label}**")
                                st.markdown(f"Outcome: {position['outcome']}")
                                st.markdown(f"Shares: {position['total_shares']:.4f}")
                                st.markdown(f"Avg Cost: ${position['avg_cost_per_share']:.4f}")
                                st.markdown(f"Total Cost: ${position['total_cost']:.4f}")
                                st.caption(f"({position['trade_count']} trades)")
                            else:
                                st.markdown("-")
                    
                    if highlight_style:
                        st.markdown('</div>', unsafe_allow_html=True)
                    st.divider()




