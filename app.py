#!/usr/bin/env python3
"""
Plug Timer Application
Flask-based web application for tracking plug assembly/disassembly times
"""

import secrets
import string
import hashlib
import qrcode
import io
import base64
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import Flask, Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app, send_from_directory
from flask_cors import CORS

# ============================================================================
# Utility Functions
# ============================================================================

def generate_short_id(length=8):
    """Generate a short unique ID using alphanumeric characters"""
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


def generate_encryption_seed():
    """Generate a cryptographic seed for data encryption"""
    return secrets.token_hex(32)


def hash_data(data: str, salt: str = None) -> str:
    """Hash data with optional salt using SHA-256"""
    if salt:
        data = f"{salt}:{data}"
    return hashlib.sha256(data.encode()).hexdigest()


def generate_qr_content(user_id: str, data_id: str = None) -> str:
    """Generate content for QR code that can be used to bind data"""
    if data_id:
        return f"plug:{user_id}:{data_id}"
    return f"plug:{user_id}"


def validate_qr_content(content: str) -> dict:
    """Validate and parse QR code content"""
    if not content.startswith("plug:"):
        return None
    
    parts = content.split(":")
    if len(parts) >= 2:
        return {
            "user_id": parts[1],
            "data_id": parts[2] if len(parts) >= 3 else None
        }
    return None


def generate_qr_code(content: str, size: int = 200) -> str:
    """Generate QR code as base64 encoded image"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    qr.add_data(content)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    buffered = io.BytesIO()
    img.save(buffered)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return f"data:image/png;base64,{img_str}"


# ============================================================================
# Database Utilities (with mock fallback for development)
# ============================================================================

class NeonDatabase:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.environ.get('NEON_DATABASE_URL')
        self.connection = None
        self._mock_data = {
            'users': {},
            'user_data': {},
            'data_shares': {}
        }
    
    def connect(self):
        """Establish database connection"""
        if self.connection and not self.connection.closed:
            return self.connection
        
        if not self.db_url:
            # For development/testing without database
            return None
        
        try:
            import psycopg2
            self.connection = psycopg2.connect(self.db_url)
            return self.connection
        except Exception:
            return None
    
    def close(self):
        """Close database connection"""
        if self.connection and not self.connection.closed:
            self.connection.close()
    
    def execute_query(self, query, params=None, fetch=True):
        """Execute a SQL query"""
        conn = self.connect()
        if not conn:
            # For development/testing without database, return mock results
            return self._mock_execute(query, params, fetch)
            
        try:
            import psycopg2
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, params or ())
            if fetch:
                result = cursor.fetchall()
                conn.commit()
                return result
            conn.commit()
            return None
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
    
    def create_tables(self):
        """Create necessary tables"""
        queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) UNIQUE NOT NULL,
                username VARCHAR(100) UNIQUE NOT NULL,
                encryption_seed TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_data (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                data_id VARCHAR(50) UNIQUE NOT NULL,
                data_name VARCHAR(200) NOT NULL,
                data_content JSONB NOT NULL,
                is_public BOOLEAN DEFAULT FALSE,
                share_id VARCHAR(50) UNIQUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS data_shares (
                id SERIAL PRIMARY KEY,
                share_id VARCHAR(50) UNIQUE NOT NULL,
                data_id VARCHAR(50) NOT NULL,
                owner_user_id VARCHAR(50) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                access_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_data_user_id ON user_data(user_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_data_data_id ON user_data(data_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_data_share_id ON user_data(share_id)
            """
        ]
        
        for query in queries:
            self.execute_query(query, fetch=False)
    
    def _mock_execute(self, query, params=None, fetch=True):
        """Mock execution for development without database"""
        query_lower = query.strip().lower()
        
        # CREATE TABLE - just return empty
        if query_lower.startswith('create table') or query_lower.startswith('create index'):
            return []
        
        # INSERT INTO users
        if 'insert into users' in query_lower:
            user_id = params[0] if params else 'test_user'
            username = params[1] if len(params) > 1 else 'test_username'
            encryption_seed = params[2] if len(params) > 2 else 'test_seed'
            
            self._mock_data['users'][user_id] = {
                'id': len(self._mock_data['users']) + 1,
                'user_id': user_id,
                'username': username,
                'encryption_seed': encryption_seed,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            return [self._mock_data['users'][user_id]]
        
        # SELECT FROM users WHERE user_id
        if 'select' in query_lower and 'from users' in query_lower and 'user_id' in query_lower:
            user_id = params[0] if params else None
            if user_id and user_id in self._mock_data['users']:
                return [self._mock_data['users'][user_id]]
            return []
        
        # SELECT FROM users WHERE username
        if 'select' in query_lower and 'from users' in query_lower and 'username' in query_lower:
            username = params[0] if params else None
            for user in self._mock_data['users'].values():
                if user['username'] == username:
                    return [user]
            return []
        
        # INSERT INTO user_data
        if 'insert into user_data' in query_lower:
            user_id = params[0] if params else 'test_user'
            data_id = params[1] if len(params) > 1 else 'test_data_id'
            data_name = params[2] if len(params) > 2 else 'test_data'
            data_content = params[3] if len(params) > 3 else {}
            share_id = params[4] if len(params) > 4 else None
            
            self._mock_data['user_data'][data_id] = {
                'id': len(self._mock_data['user_data']) + 1,
                'user_id': user_id,
                'data_id': data_id,
                'data_name': data_name,
                'data_content': data_content,
                'share_id': share_id,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            return [self._mock_data['user_data'][data_id]]
        
        # SELECT FROM user_data WHERE user_id
        if 'select' in query_lower and 'from user_data' in query_lower and 'user_id' in query_lower:
            user_id = params[0] if params else None
            results = []
            for data in self._mock_data['user_data'].values():
                if data['user_id'] == user_id:
                    results.append(data)
            return sorted(results, key=lambda x: x['created_at'], reverse=True)
        
        # SELECT FROM user_data WHERE data_id
        if 'select' in query_lower and 'from user_data' in query_lower and 'data_id' in query_lower:
            data_id = params[0] if params else None
            if data_id and data_id in self._mock_data['user_data']:
                return [self._mock_data['user_data'][data_id]]
            return []
        
        # SELECT FROM user_data WHERE share_id
        if 'select' in query_lower and 'from user_data' in query_lower and 'share_id' in query_lower:
            share_id = params[0] if params else None
            for data in self._mock_data['user_data'].values():
                if data.get('share_id') == share_id:
                    return [data]
            return []
        
        # UPDATE user_data SET share_id
        if 'update user_data' in query_lower and 'set share_id' in query_lower:
            share_id = params[0] if params else None
            data_id = params[1] if len(params) > 1 else None
            if data_id and data_id in self._mock_data['user_data']:
                self._mock_data['user_data'][data_id]['share_id'] = share_id
                return [self._mock_data['user_data'][data_id]]
            return []
        
        # INSERT INTO data_shares
        if 'insert into data_shares' in query_lower:
            share_id = params[0] if params else 'test_share'
            data_id = params[1] if len(params) > 1 else 'test_data'
            owner_user_id = params[2] if len(params) > 2 else 'test_owner'
            
            self._mock_data['data_shares'][share_id] = {
                'id': len(self._mock_data['data_shares']) + 1,
                'share_id': share_id,
                'data_id': data_id,
                'owner_user_id': owner_user_id,
                'is_active': True,
                'access_count': 0,
                'created_at': datetime.now()
            }
            return [self._mock_data['data_shares'][share_id]]
        
        # SELECT FROM data_shares WHERE share_id
        if 'select' in query_lower and 'from data_shares' in query_lower and 'share_id' in query_lower:
            share_id = params[0] if params else None
            if share_id and share_id in self._mock_data['data_shares']:
                return [self._mock_data['data_shares'][share_id]]
            return []
        
        # UPDATE data_shares SET access_count
        if 'update data_shares' in query_lower and 'access_count' in query_lower:
            share_id = params[0] if params else None
            if share_id and share_id in self._mock_data['data_shares']:
                self._mock_data['data_shares'][share_id]['access_count'] += 1
                return []
            return []
        
        # DELETE FROM user_data
        if 'delete from user_data' in query_lower:
            data_id = params[0] if params else None
            user_id = params[1] if len(params) > 1 else None
            if data_id and data_id in self._mock_data['user_data']:
                data = self._mock_data['user_data'][data_id]
                if data['user_id'] == user_id:
                    del self._mock_data['user_data'][data_id]
                    return [data]
            return []
        
        return []
    
    def get_or_create_user(self, user_id: str, username: str) -> Dict[str, Any]:
        """Get or create a user"""
        result = self.execute_query(
            "SELECT * FROM users WHERE user_id = %s", (user_id,)
        )
        
        if result:
            return result[0]
        
        seed = generate_encryption_seed()
        result = self.execute_query(
            """INSERT INTO users (user_id, username, encryption_seed)
               VALUES (%s, %s, %s) RETURNING *""",
            (user_id, username, seed)
        )
        return result[0]
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username"""
        result = self.execute_query(
            "SELECT * FROM users WHERE username = %s", (username,)
        )
        return result[0] if result else None
    
    def save_user_data(self, user_id: str, data_name: str, data_content: Dict[str, Any], share_id: str = None) -> Dict[str, Any]:
        """Save user data"""
        data_id = generate_short_id(12)
        
        result = self.execute_query(
            """INSERT INTO user_data (user_id, data_id, data_name, data_content, share_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (user_id, data_id, data_name, json.dumps(data_content), share_id)
        )
        return result[0]
    
    def get_user_data(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all data for a user"""
        result = self.execute_query(
            """SELECT * FROM user_data WHERE user_id = %s ORDER BY created_at DESC""",
            (user_id,)
        )
        return result
    
    def get_data_by_id(self, data_id: str) -> Optional[Dict[str, Any]]:
        """Get data by data_id"""
        result = self.execute_query(
            "SELECT * FROM user_data WHERE data_id = %s", (data_id,)
        )
        return result[0] if result else None
    
    def get_data_by_share_id(self, share_id: str) -> Optional[Dict[str, Any]]:
        """Get data by share_id"""
        result = self.execute_query(
            "SELECT * FROM user_data WHERE share_id = %s", (share_id,)
        )
        return result[0] if result else None
    
    def update_data_share_id(self, data_id: str, share_id: str) -> bool:
        """Update share_id for a data entry"""
        result = self.execute_query(
            """UPDATE user_data SET share_id = %s WHERE data_id = %s RETURNING *""",
            (share_id, data_id),
            fetch=True
        )
        return result is not None
    
    def create_share_link(self, data_id: str, owner_user_id: str) -> str:
        """Create a share link for data"""
        share_id = generate_short_id(12)
        
        # Update user_data with share_id
        self.update_data_share_id(data_id, share_id)
        
        # Create share record
        self.execute_query(
            """INSERT INTO data_shares (share_id, data_id, owner_user_id)
               VALUES (%s, %s, %s)""",
            (share_id, data_id, owner_user_id),
            fetch=False
        )
        
        return share_id
    
    def get_shared_data(self, share_id: str) -> Optional[Dict[str, Any]]:
        """Get shared data by share_id"""
        share_result = self.execute_query(
            "SELECT * FROM data_shares WHERE share_id = %s AND is_active = TRUE",
            (share_id,)
        )
        
        if not share_result:
            return None
        
        # Increment access count
        self.execute_query(
            "UPDATE data_shares SET access_count = access_count + 1 WHERE share_id = %s",
            (share_id,),
            fetch=False
        )
        
        # Get the actual data
        data_result = self.execute_query(
            "SELECT * FROM user_data WHERE share_id = %s",
            (share_id,)
        )
        
        return data_result[0] if data_result else None
    
    def delete_user_data(self, data_id: str, user_id: str) -> bool:
        """Delete user data"""
        result = self.execute_query(
            "DELETE FROM user_data WHERE data_id = %s AND user_id = %s RETURNING *",
            (data_id, user_id),
            fetch=True
        )
        return result is not None
    
    def update_user_data(self, data_id: str, user_id: str, data_content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update user data content"""
        result = self.execute_query(
            """UPDATE user_data SET data_content = %s, updated_at = NOW() 
               WHERE data_id = %s AND user_id = %s RETURNING *""",
            (json.dumps(data_content), data_id, user_id)
        )
        return result[0] if result else None


# Global database instance
_db_instance = None

def get_db():
    """Get database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = NeonDatabase()
        _db_instance.create_tables()
    return _db_instance


def close_db():
    """Close database connection"""
    global _db_instance
    if _db_instance:
        _db_instance.close()
        _db_instance = None


# ============================================================================
# Flask Application Setup
# ============================================================================

def fmt_filter(x):
    """Format seconds to mm:ss.s format"""
    import math
    m = math.floor(x / 60)
    s = (x % 60)
    return f"{int(m):02d}:{s:04.1f}"


app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# Neon database connection - try various environment variables
neon_url = (os.environ.get('NEON_DATABASE_URL') or
            os.environ.get('DATABASE_URL') or
            os.environ.get('POSTGRES_URL') or
            os.environ.get('POSTGRES_URL_NO_SSL') or
            os.environ.get('POSTGRES_URL_NON_POOLING') or
            None)
app.config['NEON_DATABASE_URL'] = neon_url
app.config['ENV'] = os.environ.get('ENV', 'production')

# Register custom filters
app.jinja_env.filters['fmt'] = fmt_filter

# ============================================================================
# Route Functions
# ============================================================================

def get_current_user_id():
    """Get current user ID from session"""
    return session.get('user_id')


def get_current_username():
    """Get current username from session"""
    return session.get('username')


def ensure_user_id():
    """Ensure user has an ID, create one if not"""
    if 'user_id' not in session:
        user_id = generate_short_id(8)
        username = f"user_{user_id[:6]}"
        session['user_id'] = user_id
        session['username'] = username
        
        # Create user in database
        db = get_db()
        user = db.get_or_create_user(user_id, username)
        session['encryption_seed'] = user['encryption_seed']
    
    return session['user_id'], session['username']


@app.route('/sw.js')
def service_worker():
    """Serve the service worker from the root so its scope covers the whole site"""
    res = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
    res.headers['Cache-Control'] = 'no-cache'
    res.headers['Service-Worker-Allowed'] = '/'
    return res


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/x-icon')


@app.route('/')
def index():
    """Main page - show the timer app"""
    user_id, username = ensure_user_id()
    
    # Get user data from database
    db = get_db()
    user_data = db.get_user_data(user_id)
    
    # Convert data for template
    records = []
    comments = {}
    
    for data in user_data:
        if data['data_content']:
            content = data['data_content']
            if isinstance(content, str):
                content = json.loads(content)
            
            if 'records' in content:
                records.extend(content['records'])
            if 'comments' in content:
                comments.update(content['comments'])
    
    # Get current state
    state = {}
    if user_data:
        latest = user_data[0]
        if isinstance(latest['data_content'], str):
            latest_content = json.loads(latest['data_content'])
        else:
            latest_content = latest['data_content']
        
        if 'state' in latest_content:
            state = latest_content['state']
    
    # Generate share info
    share_id = None
    share_url = None
    if user_data:
        latest_data = user_data[0]
        share_id = latest_data.get('share_id')
        if share_id:
            share_url = url_for('share_data', share_id=share_id, _external=True)
    
    # Generate QR code for user binding
    qr_content = generate_qr_content(user_id)
    qr_code = generate_qr_code(qr_content)
    
    return render_template('index.html',
                         user_id=user_id,
                         username=username,
                         records=json.dumps(records),
                         comments=json.dumps(comments),
                         state=json.dumps(state),
                         share_url=share_url,
                         share_id=share_id,
                         qr_code=qr_code,
                         qr_content=qr_content)


@app.route('/api/bind', methods=['POST'])
def bind_data():
    """Bind data to current user via QR code or short ID"""
    data = request.json
    qr_content = data.get('qr_content')
    short_id = data.get('short_id')
    
    user_id, username = ensure_user_id()
    
    if qr_content:
        # Validate QR content
        parsed = validate_qr_content(qr_content)
        if parsed and parsed.get('user_id'):
            target_user_id = parsed['user_id']
            data_id = parsed.get('data_id')
            
            # Get the target user's data
            db = get_db()
            if data_id:
                target_data = db.get_data_by_id(data_id)
            else:
                # Get latest data from target user
                target_user_data = db.get_user_data(target_user_id)
                target_data = target_user_data[0] if target_user_data else None
            
            if target_data:
                # Save a copy to current user
                data_content = target_data['data_content']
                if isinstance(data_content, str):
                    data_content = json.loads(data_content)
                
                # Create new data entry for current user
                new_data = db.save_user_data(
                    user_id=user_id,
                    data_name=f"Imported from {target_user_id}",
                    data_content=data_content
                )
                
                return jsonify({
                    'success': True,
                    'message': 'Data imported successfully',
                    'data_id': new_data['data_id']
                })
    
    return jsonify({'success': False, 'message': 'Invalid bind request'}), 400


@app.route('/api/save', methods=['POST'])
def save_data():
    """Save timer data"""
    user_id, username = ensure_user_id()
    
    data = request.json
    records = data.get('records', [])
    comments = data.get('comments', {})
    state = data.get('state', {})
    data_name = data.get('name', f"Timer Data - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Prepare data content
    data_content = {
        'records': records,
        'comments': comments,
        'state': state,
        'saved_at': datetime.now().isoformat()
    }
    
    # Save to database
    db = get_db()
    user_data = db.save_user_data(
        user_id=user_id,
        data_name=data_name,
        data_content=data_content
    )
    
    return jsonify({
        'success': True,
        'data_id': user_data['data_id'],
        'message': 'Data saved successfully'
    })


@app.route('/api/load/<data_id>', methods=['GET'])
def load_data(data_id: str):
    """Load specific data by ID"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    data = db.get_data_by_id(data_id)
    
    if not data:
        return jsonify({'success': False, 'message': 'Data not found'}), 404
    
    # Check if data belongs to user
    if data['user_id'] != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 403
    
    data_content = data['data_content']
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    return jsonify({
        'success': True,
        'data': data_content
    })


@app.route('/api/load-latest', methods=['GET'])
def load_latest_data():
    """Load latest data for current user"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    user_data = db.get_user_data(user_id)
    
    if not user_data:
        return jsonify({
            'success': True,
            'data': {'records': [], 'comments': {}, 'state': {}}
        })
    
    latest = user_data[0]
    data_content = latest['data_content']
    
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    return jsonify({
        'success': True,
        'data': data_content,
        'data_id': latest['data_id'],
        'share_id': latest.get('share_id')
    })


@app.route('/api/share', methods=['POST'])
def create_share():
    """Create a shareable link for data"""
    user_id, username = ensure_user_id()
    
    data = request.json
    data_id = data.get('data_id')
    data_name = data.get('name')
    
    if not data_id:
        # Use latest data
        db = get_db()
        user_data = db.get_user_data(user_id)
        if not user_data:
            return jsonify({'success': False, 'message': 'No data to share'}), 400
        data_id = user_data[0]['data_id']
    
    db = get_db()
    share_id = db.create_share_link(data_id, user_id)
    
    # Update data name if provided
    if data_name:
        db.update_user_data(data_id, user_id, 
                          {'name': data_name, 'updated_at': datetime.now().isoformat()})
    
    share_url = url_for('share_data', share_id=share_id, _external=True)
    
    return jsonify({
        'success': True,
        'share_id': share_id,
        'share_url': share_url,
        'qr_code': generate_qr_code(share_url)
    })


@app.route('/api/share/update-name', methods=['POST'])
def update_share_name():
    """Update share name"""
    user_id, username = ensure_user_id()
    
    data = request.json
    share_id = data.get('share_id')
    new_name = data.get('name')
    
    if not share_id or not new_name:
        return jsonify({'success': False, 'message': 'Missing parameters'}), 400
    
    db = get_db()
    shared_data = db.get_data_by_share_id(share_id)
    
    if not shared_data:
        return jsonify({'success': False, 'message': 'Share not found'}), 404
    
    if shared_data['user_id'] != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    # Update data name
    data_content = shared_data['data_content']
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    data_content['name'] = new_name
    
    db.update_user_data(shared_data['data_id'], user_id, data_content)
    
    return jsonify({'success': True, 'message': 'Name updated'})


@app.route('/share/<share_id>')
def share_data(share_id: str):
    """Share data page - show shared timer data"""
    db = get_db()
    shared_data = db.get_shared_data(share_id)
    
    if not shared_data:
        return render_template('share_error.html', message="Share not found or expired"), 404
    
    data_content = shared_data['data_content']
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    # Generate QR code for this share
    share_url = url_for('share_data', share_id=share_id, _external=True)
    qr_code = generate_qr_code(share_url)
    
    return render_template('share.html',
                         share_id=share_id,
                         share_url=share_url,
                         data=data_content,
                         qr_code=qr_code,
                         owner_username=shared_data.get('username', 'Unknown'))


@app.route('/share/<share_id>/data')
def share_data_json(share_id: str):
    """Get shared data as JSON"""
    db = get_db()
    shared_data = db.get_shared_data(share_id)
    
    if not shared_data:
        return jsonify({'success': False, 'message': 'Share not found'}), 404
    
    data_content = shared_data['data_content']
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    return jsonify({
        'success': True,
        'data': data_content,
        'share_id': share_id,
        'owner_user_id': shared_data['user_id']
    })


@app.route('/api/user/info', methods=['GET'])
def user_info():
    """Get current user information"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    user = db.get_or_create_user(user_id, username)
    
    return jsonify({
        'user_id': user_id,
        'username': username,
        'encryption_seed': user['encryption_seed'],
        'created_at': user['created_at'].isoformat() if user['created_at'] else None
    })


@app.route('/api/user/set-username', methods=['POST'])
def set_username():
    """Set a custom username"""
    user_id, current_username = ensure_user_id()
    
    data = request.json
    new_username = data.get('username')
    
    if not new_username:
        return jsonify({'success': False, 'message': 'Username is required'}), 400
    
    # Check if username is already taken
    db = get_db()
    existing_user = db.get_user_by_username(new_username)
    
    if existing_user and existing_user['user_id'] != user_id:
        return jsonify({'success': False, 'message': 'Username already taken'}), 400
    
    # Update username
    db.execute_query(
        "UPDATE users SET username = %s WHERE user_id = %s",
        (new_username, user_id),
        fetch=False
    )
    
    session['username'] = new_username
    
    return jsonify({
        'success': True,
        'username': new_username,
        'message': 'Username updated successfully'
    })


@app.route('/api/data/list', methods=['GET'])
def list_user_data():
    """List all data entries for current user"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    user_data = db.get_user_data(user_id)
    
    result = []
    for data in user_data:
        data_content = data['data_content']
        if isinstance(data_content, str):
            data_content = json.loads(data_content)
        
        result.append({
            'data_id': data['data_id'],
            'data_name': data['data_name'],
            'created_at': data['created_at'].isoformat() if data['created_at'] else None,
            'updated_at': data['updated_at'].isoformat() if data['updated_at'] else None,
            'share_id': data.get('share_id'),
            'record_count': len(data_content.get('records', []))
        })
    
    return jsonify({'success': True, 'data': result})


@app.route('/api/data/delete/<data_id>', methods=['POST'])
def delete_data(data_id: str):
    """Delete a data entry"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    success = db.delete_user_data(data_id, user_id)
    
    if success:
        return jsonify({'success': True, 'message': 'Data deleted'})
    else:
        return jsonify({'success': False, 'message': 'Data not found or unauthorized'}), 404


@app.route('/api/import', methods=['POST'])
def import_data():
    """Import data from file or URL"""
    user_id, username = ensure_user_id()
    
    if 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        try:
            data = json.load(file)
            data_name = data.get('name', f"Imported - {datetime.now().strftime('%Y-%m-%d')}")
            
            db = get_db()
            user_data = db.save_user_data(
                user_id=user_id,
                data_name=data_name,
                data_content=data
            )
            
            return jsonify({
                'success': True,
                'data_id': user_data['data_id'],
                'message': 'Data imported successfully'
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 400
    
    return jsonify({'success': False, 'message': 'No data provided'}), 400


@app.route('/api/export/<data_id>', methods=['GET'])
def export_data(data_id: str):
    """Export data as JSON file"""
    user_id, username = ensure_user_id()
    
    db = get_db()
    data = db.get_data_by_id(data_id)
    
    if not data:
        return jsonify({'success': False, 'message': 'Data not found'}), 404
    
    if data['user_id'] != user_id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data_content = data['data_content']
    if isinstance(data_content, str):
        data_content = json.loads(data_content)
    
    # Return as downloadable file
    from flask import Response
    response = Response(
        json.dumps(data_content, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename=plug-data-{data_id}.json'}
    )
    return response


@app.before_request
def before_request():
    """Initialize session secret key"""
    if 'secret_key' not in session:
        session['secret_key'] = os.urandom(16).hex()


@app.after_request
def after_request(response):
    """Ensure session is saved"""
    session.modified = True
    return response


# ============================================================================
# For Vercel deployment
# ============================================================================
application = app
