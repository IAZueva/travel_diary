"""Учебный дневник путешествий: аккаунты, записи, галерея, расходы и геокоординаты."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from functools import wraps
from urllib.parse import urlparse
from flask import Flask,abort,flash,g,redirect,render_template,request,session,url_for
from werkzeug.security import generate_password_hash,check_password_hash
BASE=Path(__file__).resolve().parent
app=Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY','dev-change-me'),DATABASE=os.environ.get('DATABASE',str(BASE/'travel.sqlite3')))
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trips(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,title TEXT NOT NULL,country TEXT NOT NULL,place TEXT NOT NULL,description TEXT NOT NULL,latitude REAL,longitude REAL,image_url TEXT,budget INTEGER NOT NULL DEFAULT 0,cultural_sites TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
'''

def db():
    if 'db' not in g:
        g.db=sqlite3.connect(app.config['DATABASE']);g.db.row_factory=sqlite3.Row;g.db.execute('PRAGMA foreign_keys=ON')
    return g.db
@app.teardown_appcontext
def close(err):
    con=g.pop('db',None)
    if con:con.close()
def init_db():
    Path(app.config['DATABASE']).parent.mkdir(parents=True,exist_ok=True)
    db().executescript(SCHEMA)
def login_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        if not session.get('uid'):flash('Сначала войдите.');return redirect(url_for('login'))
        return fn(*a,**kw)
    return wrap
@app.context_processor
def ctx():return {'uid':session.get('uid'),'username':session.get('username')}
@app.template_filter('money')
def money(cents):return f'{cents/100:,.2f}'.replace(',',' ').replace('.',',')+' ₽'

def trip_or_404(tid):
    t=db().execute('SELECT t.*,u.username FROM trips t JOIN users u ON u.id=t.user_id WHERE t.id=?',(tid,)).fetchone()
    if not t:abort(404)
    return t

@app.get('/')
def index():
    country=request.args.get('country','').strip();query=request.args.get('q','').strip()
    rows=db().execute('SELECT t.*,u.username FROM trips t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC').fetchall()
    if country:rows=[r for r in rows if country.casefold() in r['country'].casefold()]
    if query:rows=[r for r in rows if query.casefold() in (r['title']+' '+r['place']+' '+r['description']).casefold()]
    return render_template('index.html',rows=rows,country=country,query=query)

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        uname=request.form.get('username','').strip();pwd=request.form.get('password','')
        if len(uname)<3 or len(pwd)<8:flash('Имя от 3 символов, пароль от 8.')
        else:
            try:
                with db():db().execute('INSERT INTO users(username,password) VALUES(?,?)',(uname,generate_password_hash(pwd)))
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:flash('Имя уже занято.')
    return render_template('auth.html',mode='Регистрация')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=db().execute('SELECT * FROM users WHERE username=?',(request.form.get('username',''),)).fetchone()
        if u and check_password_hash(u['password'],request.form.get('password','')):
            session.clear();session.update(uid=u['id'],username=u['username']);return redirect(url_for('index'))
        flash('Неверный логин или пароль.')
    return render_template('auth.html',mode='Вход')

@app.post('/logout')
def logout():session.clear();return redirect(url_for('index'))

def parse_trip(form):
    title=form.get('title','').strip();country=form.get('country','').strip();place=form.get('place','').strip();desc=form.get('description','').strip()
    image=form.get('image_url','').strip();sites=form.get('cultural_sites','').strip()
    if not title or not country or not place or not desc:raise ValueError('Заполните обязательные поля.')
    if image and urlparse(image).scheme not in ('https','http'):raise ValueError('Ссылка на фото должна начинаться с https:// или http://.')
    lat_s=form.get('latitude','').strip();lon_s=form.get('longitude','').strip()
    if bool(lat_s)!=bool(lon_s):raise ValueError('Укажите обе координаты либо оставьте обе пустыми.')
    lat=float(lat_s) if lat_s else None;lon=float(lon_s) if lon_s else None
    if lat is not None and not (-90<=lat<=90 and -180<=lon<=180):raise ValueError('Некорректные координаты.')
    cost=float(form.get('budget','0').replace(',','.'))
    if cost<0 or cost>1_000_000_000:raise ValueError('Недопустимая стоимость.')
    return title,country,place,desc,lat,lon,image,round(cost*100),sites

@app.route('/trip/new',methods=['GET','POST'])
@login_required
def new_trip():
    if request.method=='POST':
        try:
            fields=parse_trip(request.form)
            with db():db().execute('INSERT INTO trips(user_id,title,country,place,description,latitude,longitude,image_url,budget,cultural_sites) VALUES(?,?,?,?,?,?,?,?,?,?)',(session['uid'],*fields))
            return redirect(url_for('index'))
        except (ValueError,OverflowError) as ex:flash(str(ex))
    return render_template('form.html',trip=None)

@app.route('/trip/<int:tid>')
def show_trip(tid):return render_template('trip.html',trip=trip_or_404(tid))

@app.route('/trip/<int:tid>/edit',methods=['GET','POST'])
@login_required
def edit_trip(tid):
    t=trip_or_404(tid)
    if t['user_id']!=session['uid']:abort(403)
    if request.method=='POST':
        try:
            fields=parse_trip(request.form)
            with db():db().execute('UPDATE trips SET title=?,country=?,place=?,description=?,latitude=?,longitude=?,image_url=?,budget=?,cultural_sites=? WHERE id=?',(*fields,tid))
            return redirect(url_for('show_trip',tid=tid))
        except (ValueError,OverflowError) as ex:flash(str(ex))
    return render_template('form.html',trip=t)

@app.post('/trip/<int:tid>/delete')
@login_required
def delete_trip(tid):
    t=trip_or_404(tid)
    if t['user_id']!=session['uid']:abort(403)
    with db():db().execute('DELETE FROM trips WHERE id=?',(tid,))
    return redirect(url_for('index'))

with app.app_context():init_db()
if __name__=='__main__':app.run(debug=os.environ.get('FLASK_DEBUG')=='1')
