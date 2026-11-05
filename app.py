import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY', 'local-development-only-change-before-deploy'), DATABASE=str(BASE_DIR / 'skillswap.db'), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
CATEGORIES = {'skill': 'Skill Exchange', 'job': 'Jobs', 'item': 'Item Exchange'}
AREAS = ['Colombo','Gampaha','Ragama','Negombo','Kandy','Galle','Matara','Kurunegala','Jaffna','Kalutara','Other']

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

@app.teardown_appcontext
def close_db(_error):
    connection = g.pop('db', None)
    if connection is not None: connection.close()

def init_db():
    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            area TEXT NOT NULL,
            skills TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category TEXT NOT NULL CHECK(category IN ('skill','job','item')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            area TEXT NOT NULL,
            offer TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);
        CREATE INDEX IF NOT EXISTS idx_posts_area ON posts(area);
        ''')
        db().commit()

@app.before_request
def load_user_and_csrf():
    g.user = None
    if 'csrf_token' not in session:
        import secrets
        session['csrf_token'] = secrets.token_urlsafe(32)
    if session.get('user_id'):
        g.user = db().execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if g.user is None: session.pop('user_id', None)
    if request.method == 'POST':
        from hmac import compare_digest
        if not compare_digest(str(session['csrf_token']), str(request.form.get('csrf_token',''))):
            abort(400, description='Invalid form token. Refresh and try again.')

@app.context_processor
def common():
    return dict(categories=CATEGORIES, areas=AREAS, csrf_token=session.get('csrf_token',''))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def get_post(post_id):
    post = db().execute('''SELECT p.*, u.name AS author FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?''', (post_id,)).fetchone()
    if post is None: abort(404)
    return post

@app.route('/')
def home():
    counts = {row['category']: row['n'] for row in db().execute('SELECT category, COUNT(*) n FROM posts GROUP BY category')}
    recent = db().execute('''SELECT p.*,u.name AS author FROM posts p JOIN users u ON p.user_id=u.id ORDER BY p.id DESC LIMIT 6''').fetchall()
    return render_template('home.html', recent=recent, counts=counts)

@app.route('/explore')
def explore():
    category = request.args.get('category','').strip()
    area = request.args.get('area','').strip()
    q = request.args.get('q','').strip()[:100]
    sql = 'SELECT p.*,u.name AS author FROM posts p JOIN users u ON p.user_id=u.id WHERE 1=1'
    params=[]
    if category in CATEGORIES:
        sql += ' AND p.category=?'; params.append(category)
    if area:
        sql += ' AND p.area LIKE ?'; params.append('%'+area+'%')
    if q:
        sql += ' AND (p.title LIKE ? OR p.description LIKE ? OR p.offer LIKE ?)'; params += ['%'+q+'%']*3
    sql += ' ORDER BY p.id DESC LIMIT 150'
    posts = db().execute(sql,params).fetchall()
    return render_template('explore.html',posts=posts, category=category, area=area,q=q)

@app.route('/register', methods=['GET','POST'])
def register():
    if g.user: return redirect(url_for('dashboard'))
    if request.method=='POST':
        name=request.form.get('name','').strip()[:70]
        email=request.form.get('email','').strip().lower()[:150]
        password=request.form.get('password','')
        area=request.form.get('area','').strip()[:70]
        skills=request.form.get('skills','').strip()[:250]
        if not name or '@' not in email or not area or len(password)<8:
            flash('Complete all required fields. Password must have 8+ characters.','error')
        else:
            try:
                cur=db().execute('INSERT INTO users(name,email,password_hash,area,skills) VALUES(?,?,?,?,?)', (name,email,generate_password_hash(password),area,skills))
                db().commit()
                session.clear()
                import secrets
                session['csrf_token']=secrets.token_urlsafe(32)
                session['user_id']=cur.lastrowid
                flash('Account created successfully!','success')
                return redirect(url_for('dashboard'))
            except sqlite3.IntegrityError:
                flash('That email is already registered.','error')
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET','POST'])
def login():
    if g.user: return redirect(url_for('dashboard'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password','')
        user=db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if user and check_password_hash(user['password_hash'],password):
            session.clear()
            import secrets
            session['csrf_token']=secrets.token_urlsafe(32)
            session['user_id']=user['id']
            flash('Welcome back!','success')
            return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','error')
    return render_template('auth.html',mode='login')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    flash('You have logged out.','success')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    posts=db().execute('SELECT * FROM posts WHERE user_id=? ORDER BY id DESC',(g.user['id'],)).fetchall()
    jobs=db().execute("SELECT p.*,u.name AS author FROM posts p JOIN users u ON p.user_id=u.id WHERE p.category='job' AND p.user_id!=? ORDER BY p.id DESC LIMIT 100",(g.user['id'],)).fetchall()
    user_skills=[s.strip().lower() for s in g.user['skills'].split(',') if len(s.strip())>=2]
    def score(job):
        text=(job['title']+' '+job['description']).lower()
        return (5 if g.user['area'].lower() in job['area'].lower() else 0)+sum(3 for s in user_skills if s in text)
    matches=sorted((j for j in jobs if score(j)>0),key=score,reverse=True)[:3]
    return render_template('dashboard.html',posts=posts,matches=matches)

@app.route('/post/new', methods=['GET','POST'])
@login_required
def new_post():
    if request.method=='POST':
        data, error=validate_post()
        if error: flash(error,'error')
        else:
            cur=db().execute('INSERT INTO posts(user_id,category,title,description,area,offer) VALUES(?,?,?,?,?,?)',(g.user['id'],*data))
            db().commit()
            flash('Your post is live!','success')
            return redirect(url_for('post_detail',post_id=cur.lastrowid))
    return render_template('post_form.html',post=None)

def validate_post():
    category=request.form.get('category','').strip()
    title=request.form.get('title','').strip()
    description=request.form.get('description','').strip()
    area=request.form.get('area','').strip()
    offer=request.form.get('offer','').strip()
    if category not in CATEGORIES: return None,'Choose a valid category.'
    if not (4<=len(title)<=100): return None,'Title must be 4–100 characters.'
    if not (10<=len(description)<=2000): return None,'Description must be 10–2000 characters.'
    if not (2<=len(area)<=70): return None,'Enter a valid area.'
    if len(offer)>160: return None,'Exchange/requirements text must be under 160 characters.'
    return (category,title,description,area,offer),None

@app.route('/post/<int:post_id>')
def post_detail(post_id):
    return render_template('detail.html',post=get_post(post_id))

@app.route('/post/<int:post_id>/edit',methods=['GET','POST'])
@login_required
def edit_post(post_id):
    post=get_post(post_id)
    if post['user_id']!=g.user['id']: abort(403)
    if request.method=='POST':
        data,error=validate_post()
        if error: flash(error,'error')
        else:
            db().execute('''UPDATE posts SET category=?,title=?,description=?,area=?,offer=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?''',(*data,post_id,g.user['id']))
            db().commit()
            flash('Post updated successfully!','success')
            return redirect(url_for('post_detail',post_id=post_id))
    return render_template('post_form.html',post=post)

@app.route('/post/<int:post_id>/delete',methods=['POST'])
@login_required
def delete_post(post_id):
    post=get_post(post_id)
    if post['user_id']!=g.user['id']: abort(403)
    db().execute('DELETE FROM posts WHERE id=? AND user_id=?',(post_id,g.user['id']))
    db().commit()
    flash('Post deleted.','success')
    return redirect(url_for('dashboard'))

@app.errorhandler(404)
def missing(_): return render_template('error.html',code=404,message='Page not found'),404
@app.errorhandler(403)
def forbidden(_): return render_template('error.html',code=403,message='You cannot edit this post'),403
@app.errorhandler(400)
def bad_request(_): return render_template('error.html',code=400,message='Invalid request. Refresh the page.'),400

init_db()
if __name__=='__main__':
    app.run(debug=True)
