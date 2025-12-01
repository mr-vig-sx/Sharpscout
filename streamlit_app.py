import streamlit as st
import requests
import json
import os
import pandas as pd
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

# File to store wallet addresses
DATA_DIR = os.path.expanduser('~/.sharpscout')
WALLETS_FILE = os.path.join(DATA_DIR, 'wallets.json')

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize session state
if 'wallets' not in st.session_state:
    # Load wallets from file on first run
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            wallets_data = json.load(f)
            # Convert old format (list of strings) to new format (list of dicts)
            if wallets_data and isinstance(wallets_data[0], str):
                st.session_state.wallets = [{'address': addr, 'label': ''} for addr in wallets_data]
            else:
                st.session_state.wallets = wallets_data
    else:
        st.session_state.wallets = []

if 'market_cache' not in st.session_state:
    st.session_state.market_cache = {}

def load_wallets():
    """Load wallet addresses from file"""
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            wallets = json.load(f)
            # Convert old format (list of strings) to new format (list of dicts)
            if wallets and isinstance(wallets[0], str):
                return [{'address': addr, 'label': ''} for addr in wallets]
            return wallets
    return []

def save_wallets(wallets):
    """Save wallet addresses to file"""
    with open(WALLETS_FILE, 'w') as f:
        json.dump(wallets, f, indent=2)
    st.session_state.wallets = wallets

@st.cache_data(ttl=300)  # Cache for 5 minutes (shorter for price data)
def fetch_market_info_cached(condition_id):
    """Fetch market name, event date, and current prices from Polymarket API (cached)"""
    if not condition_id:
        return {'name': 'Unknown Market', 'date': None, 'prices': {}}
    
    market_name = None
    event_date = None
    outcome_prices = {}
    
    # Try Data API first (faster)
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
                market_name = event_data.get('title') or event_data.get('question') or event_data.get('slug')
                event_date = event_data.get('endDate') or event_data.get('startDate') or event_data.get('date') or event_data.get('eventDate')
                
                # Get outcome prices if available
                if 'outcomes' in event_data:
                    for outcome in event_data['outcomes']:
                        outcome_name = outcome.get('title') or outcome.get('name')
                        price = outcome.get('price') or outcome.get('lastPrice') or outcome.get('currentPrice')
                        if outcome_name and price is not None:
                            outcome_prices[outcome_name] = float(price)
            
            if market_name and market_name != 'Unknown Market':
                return {'name': market_name, 'date': event_date, 'prices': outcome_prices}
    except Exception:
        pass
    
    # Try to get prices from markets endpoint
    try:
        url = f"https://data-api.polymarket.com/markets"
        params = {'conditionId': condition_id}
        response = requests.get(url, params=params, timeout=3)
        if response.status_code == 200:
            data = response.json()
            markets = data if isinstance(data, list) else (data.get('data', []) if isinstance(data, dict) else [])
            if markets:
                market = markets[0]
                if not market_name:
                    market_name = market.get('question') or market.get('title')
                # Get outcome prices
                if 'tokens' in market:
                    for token in market['tokens']:
                        outcome_name = token.get('outcome') or token.get('title')
                        price = token.get('price') or token.get('lastPrice')
                        if outcome_name and price is not None:
                            outcome_prices[outcome_name] = float(price)
    except Exception:
        pass
    
    # Fallback to shortened condition_id
    short_id = condition_id[:16] + '...' if len(condition_id) > 16 else condition_id
    return {'name': short_id, 'date': None, 'prices': {}}

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
        response = requests.get(url, params=params, timeout=10)
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

def fetch_polymarket_trades(wallet_address):
    """Fetch trades and enrich with market info"""
    trades = fetch_polymarket_trades_cached(wallet_address)
    
    if not trades:
        return []
    
    # Batch fetch market info for unique condition IDs only
    unique_condition_ids = set()
    for trade in trades:
        condition_id = trade.get('conditionId') or trade.get('condition_id') or trade.get('market')
        if condition_id:
            unique_condition_ids.add(condition_id)
    
    # Pre-fetch market info for all unique condition IDs
    market_info_cache = {}
    for condition_id in unique_condition_ids:
        market_info_cache[condition_id] = fetch_market_info(condition_id)
    
    # Enrich trades with market names and dates
    for trade in trades:
        condition_id = trade.get('conditionId') or trade.get('condition_id') or trade.get('market')
        market_name = trade.get('marketName') or trade.get('market_name') or trade.get('question') or trade.get('title')
        market_date = trade.get('eventDate') or trade.get('endDate') or trade.get('startDate')
        
        if condition_id and condition_id in market_info_cache:
            market_info = market_info_cache[condition_id]
            if not market_name:
                market_name = market_info['name']
            if not market_date:
                market_date = market_info['date']
        
        trade['condition_id'] = condition_id
        trade['market_name'] = market_name or 'Unknown Market'
        trade['market_date'] = market_date
    
    return trades

def aggregate_position(trades):
    """Aggregate trades into a single position with avg cost and total cost"""
    if not trades:
        return None
    
    total_shares = 0
    total_cost = 0
    outcomes = set()
    
    for trade in trades:
        amount = float(trade.get('amount', 0) or trade.get('size', 0) or trade.get('quantity', 0) or 0)
        if amount == 0:
            continue
            
        price = float(trade.get('price', 0) or trade.get('priceNum', 0) or trade.get('fillPrice', 0) or 0)
        side = (trade.get('side', '') or trade.get('type', '') or '').lower()
        is_maker = trade.get('isMaker', False)
        outcome = trade.get('outcome') or trade.get('outcomeName', 'Unknown')
        outcomes.add(outcome)
        
        is_buy = False
        if side in ['buy', 'b', 'long', 'bid']:
            is_buy = True
        elif side in ['sell', 's', 'short', 'ask', 'ask_order']:
            is_buy = False
        elif is_maker:
            is_buy = True
        else:
            is_buy = True
        
        if is_buy:
            total_shares += amount
            total_cost += amount * price
        else:
            total_shares -= amount
            total_cost -= amount * price
    
    if abs(total_shares) < 0.0001:
        return None
    
    avg_cost = total_cost / total_shares if total_shares != 0 else 0
    outcome_str = ', '.join(sorted(outcomes)) if len(outcomes) > 0 else 'Unknown'
    
    return {
        'outcome': outcome_str,
        'total_shares': abs(total_shares),
        'avg_cost_per_share': avg_cost,
        'total_cost': abs(total_cost),
        'position_type': 'Long' if total_shares > 0 else 'Short',
        'trade_count': len(trades)
    }

def get_all_positions():
    """Fetch and aggregate positions from all wallets"""
    wallets = st.session_state.wallets if st.session_state.wallets else []
    if not wallets:
        return []
    
    return get_all_positions_cached(wallets)

@st.cache_data(ttl=300)  # Cache positions for 5 minutes
def get_all_positions_cached(wallets_list):
    """Fetch and aggregate positions from all wallets (cached)"""
    wallets = wallets_list
    if not wallets:
        return []
    
    markets_dict = {}
    
    for wallet_obj in wallets:
        if isinstance(wallet_obj, dict):
            wallet_address = wallet_obj['address']
            wallet_label = wallet_obj.get('label', wallet_address[:10])
        else:
            wallet_address = wallet_obj
            wallet_label = wallet_address[:10]
        
        trades = fetch_polymarket_trades(wallet_address)
        
        # Group trades by market and outcome
        market_outcome_trades = {}
        for trade in trades:
            market_name = trade.get('market_name') or trade.get('market') or trade.get('conditionId') or trade.get('condition_id') or 'Unknown Market'
            condition_id = trade.get('condition_id') or trade.get('conditionId') or trade.get('market')
            outcome = trade.get('outcome') or trade.get('outcomeName', 'Unknown')
            market_date = trade.get('market_date')
            
            if market_name not in market_outcome_trades:
                market_outcome_trades[market_name] = {'date': market_date, 'outcomes': {}}
            
            if outcome not in market_outcome_trades[market_name]['outcomes']:
                market_outcome_trades[market_name]['outcomes'][outcome] = []
            
            trade['wallet_address'] = wallet_address
            trade['wallet_label'] = wallet_label
            trade['condition_id'] = condition_id
            market_outcome_trades[market_name]['outcomes'][outcome].append(trade)
        
        # Aggregate positions for each market
        for market_name, market_data in market_outcome_trades.items():
            if market_name not in markets_dict:
                markets_dict[market_name] = {
                    'date': market_data.get('date'),
                    'wallets': {},
                    'market_info': None  # Will store market info for price checking
                }
            
            outcome_positions = {}
            for outcome, trades_list in market_data['outcomes'].items():
                position = aggregate_position(trades_list)
                if position:
                    outcome_positions[outcome] = position
            
            if outcome_positions:
                best_outcome = max(outcome_positions.items(), key=lambda x: x[1]['total_cost'])
                markets_dict[market_name]['wallets'][wallet_label] = best_outcome[1]
                
                # Store market info for price checking (use first trade's condition_id)
                if not markets_dict[market_name]['market_info'] and market_data['outcomes']:
                    first_trade = list(market_data['outcomes'].values())[0][0]
                    condition_id = first_trade.get('condition_id')
                    if condition_id:
                        markets_dict[market_name]['market_info'] = fetch_market_info(condition_id)
    
    # Convert to list format and filter by date
    markets_list = []
    today = datetime.now().date()
    
    # Optimized date parsing function
    def parse_date(date_str):
        """Quick date parsing with caching"""
        if not date_str:
            return None
        try:
            if isinstance(date_str, (int, float)):
                return datetime.fromtimestamp(date_str / 1000 if date_str > 1e10 else date_str).date()
            date_str = str(date_str)
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
            return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        except Exception:
            return None
    
    for market_name, market_data in markets_dict.items():
        wallet_positions = market_data.get('wallets', {})
        market_date_str = market_data.get('date')
        market_info = market_data.get('market_info', {})
        
        # Check if market is resolved based on prices
        is_resolved = False
        if market_info and market_info.get('prices'):
            prices = market_info.get('prices', {})
            # If any outcome price is < 0.01 or > 0.99, market is resolved
            for outcome_name, price in prices.items():
                if price < 0.01 or price > 0.99:
                    is_resolved = True
                    break
        
        # Also check date as backup filter
        include_market = not is_resolved
        if not is_resolved and market_date_str:
            market_date = parse_date(market_date_str)
            if market_date and market_date < today:
                include_market = False
        
        if include_market:
            markets_list.append({
                'market_name': market_name,
                'market_date': market_date_str,
                'wallets': wallet_positions,
                'wallet_count': len(wallet_positions)
            })
    
    # Calculate total wager (sum of all wallet positions' total_cost) for each market
    for market in markets_list:
        total_wager = sum(pos['total_cost'] for pos in market['wallets'].values())
        market['total_wager'] = total_wager
    
    return markets_list

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
    # Sort options
    sort_option = st.selectbox(
        "Sort by:",
        ["Most Wallets (2/3 or 3/3)", "Total Wager (High to Low)", "Total Wager (Low to High)", "Market Name (A-Z)"],
        key="sort_option"
    )
    
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 Refresh Positions", use_container_width=True):
            if 'market_cache' in st.session_state:
                st.session_state.market_cache.clear()
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
        # Sort positions based on selected option
        if sort_option == "Most Wallets (2/3 or 3/3)":
            positions.sort(key=lambda x: (-x['wallet_count'], x['market_name']))
        elif sort_option == "Total Wager (High to Low)":
            positions.sort(key=lambda x: (-x.get('total_wager', 0), x['market_name']))
        elif sort_option == "Total Wager (Low to High)":
            positions.sort(key=lambda x: (x.get('total_wager', 0), x['market_name']))
        elif sort_option == "Market Name (A-Z)":
            positions.sort(key=lambda x: x['market_name'])
        
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



