# Importazioni necessarie
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
import functools # Per i decoratori di ruolo
from datetime import datetime # Per i timestamp dei like e commenti

# Nuove importazioni per il Chatbot AI
from dotenv import load_dotenv
import google.generativeai as genai

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# --- Configurazione dell'App Flask ---
app = Flask(__name__)
# La chiave segreta viene caricata dal file .env per sicurezza
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'una_chiave_segreta_default_molto_forte_e_complessa_E_UNICA')
# Configura il database SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configurazione per gli upload di file
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Assicurati che la cartella degli upload esista
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Inizializza il database
db = SQLAlchemy(app)

# --- Configurazione Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # La rotta a cui reindirizzare se l'utente non è loggato

@login_manager.user_loader
def load_user(user_id):
    """Ricarica l'oggetto utente dalla sessione."""
    return User.query.get(int(user_id))

# --- Configurazione Google Gemini AI ---
# La chiave API viene caricata da .env
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    print("ERRORE: La chiave API di Google Gemini non è stata trovata. Assicurati che GOOGLE_API_KEY sia impostata nel tuo file .env")
    # In un'applicazione di produzione, potresti voler sollevare un'eccezione o gestire l'errore in altro modo.
    # Per ora, terminiamo l'applicazione per evidenziare il problema.
    exit(1)
genai.configure(api_key=GEMINI_API_KEY)
# Utilizziamo un modello più recente e stabile per il chatbot
# Controlla l'output di `check_models.py` per i nomi esatti disponibili
try:
    model = genai.GenerativeModel('gemini-1.5-flash') # Modello consigliato per la maggior parte dei casi
except Exception as e:
    print(f"Errore durante l'inizializzazione del modello Gemini. Prova con 'gemini-1.5-pro' o un altro modello disponibile. Errore: {e}")
    model = None # Se il modello non si carica, le funzionalità del chatbot saranno disabilitate


# --- Funzioni di Utility per l'Upload ---
def allowed_file(filename):
    """Controlla se l'estensione del file è permessa."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Decoratore per i Ruoli Utente ---
def role_required(role='admin'):
    """
    Decoratore per limitare l'accesso alle rotte in base al ruolo dell'utente.
    Esempio: @role_required(role='admin')
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Devi effettuare l\'accesso per accedere a questa pagina.', 'warning')
                return redirect(url_for('login', next=request.url))
            if role == 'admin' and not current_user.is_admin:
                flash('Non hai i permessi necessari per accedere a questa pagina.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# --- Modelli del Database ---

class Article(db.Model):
    """Modello per gli articoli del blog."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, nullable=False, default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # L'autore dell'articolo
    image_filename = db.Column(db.String(100), nullable=True) # Nome del file immagine associato all'articolo
    views = db.Column(db.Integer, default=0) # Conteggio delle visualizzazioni dell'articolo

    # 'author' qui è il nome della proprietà sul modello Article.
    # È creato dal backref='author' nella relazione 'articles' in User.

    def __repr__(self):
        return f'<Article {self.id}: {self.title}>'

class User(db.Model, UserMixin):
    """Modello per gli utenti del sito."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # Campi aggiuntivi per il profilo utente
    bio = db.Column(db.Text, nullable=True)
    profile_picture = db.Column(db.String(100), nullable=True) # Nome del file immagine profilo
    # Campo per i ruoli utente (True se admin, False altrimenti)
    is_admin = db.Column(db.Boolean, default=False)

    # Relazione 1:molti Articoli per un Utente
    # user.articles -> lista di articoli scritti dall'utente
    # article.author -> l'oggetto utente che ha scritto l'articolo
    articles = db.relationship('Article', backref='author', lazy=True)

    # Relazione 1:molti Commenti per un Utente
    # user.comments_posted -> lista di commenti scritti dall'utente
    # comment.comment_author -> l'oggetto utente che ha scritto il commento
    comments_posted = db.relationship('Comment', backref='comment_author', lazy=True)

    # Relazione 1:molti Likes per un Utente
    # user.likes_given -> lista di likes dati dall'utente
    # like.liking_user -> l'oggetto utente che ha messo il like
    likes_given = db.relationship('Like', backref='liking_user', lazy=True)


    def set_password(self, password):
        """Genera l'hash della password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica la password fornita con l'hash memorizzato."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Comment(db.Model):
    """Modello per i commenti agli articoli."""
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, nullable=False, default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)

    # Relazione: un commento appartiene a un articolo
    # E dall'articolo, puoi accedere ai suoi commenti tramite article.comments
    article = db.relationship('Article', backref=db.backref('comments', lazy=True))

    # La proprietà 'comment_author' su Comment viene creata dal backref in User.comments_posted

    def __repr__(self):
        # Utilizza la relazione 'comment_author' che viene creata tramite il backref
        # dalla relazione 'comments_posted' nel modello User.
        return f'<Comment {self.id} by {self.comment_author.username}>'

class Like(db.Model):
    """Modello per i "Mi Piace" agli articoli."""
    # Chiave primaria composta per garantire un solo like per utente per articolo
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=db.func.now())

    # Relazione: un like appartiene a un articolo
    # E dall'articolo, puoi accedere ai suoi like tramite article.likes
    article = db.relationship('Article', backref=db.backref('likes', lazy=True))

    # La proprietà 'liking_user' su Like viene creata dal backref in User.likes_given

    def __repr__(self):
        # Utilizza la relazione 'liking_user' che viene creata tramite il backref
        # dalla relazione 'likes_given' nel modello User.
        return f'<Like User:{self.liking_user.username} Article:{self.article.title}>'


# --- Creazione/Aggiornamento del Database ---
# IMPORTANTE: Se hai già un database 'site.db' esistente e hai aggiunto/modificato campi,
# dovrai eliminarlo e ricrearlo (solo la prima volta dopo le modifiche ai modelli).
with app.app_context():
    db.create_all()
    print("Database creato o già esistente.")


# --- Routing dell'Applicazione ---

@app.route('/')
def index():
    """Mostra la homepage con gli articoli paginati e la funzionalità di ricerca."""
    page = request.args.get('page', 1, type=int) # Ottiene il numero di pagina dall'URL, default 1
    per_page = 5 # Definisci quanti articoli vuoi per pagina

    query_filter = Article.query

    search_query = request.args.get('q') # Ottiene il parametro di ricerca 'q' dall'URL
    if search_query:
        # Applica il filtro di ricerca
        query_filter = query_filter.filter(
            (Article.title.ilike(f'%{search_query}%')) |
            (Article.content.ilike(f'%{search_query}%'))
        )
        flash(f"Risultati per la ricerca: '{search_query}'", 'info')

    # Applica l'ordinamento e la paginazione
    articles_pagination = query_filter.order_by(Article.pub_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    articles = articles_pagination.items # Gli articoli per la pagina corrente

    return render_template('index.html', articles=articles, pagination=articles_pagination, query=search_query)

@app.route('/article/<int:article_id>')
def article_detail(article_id):
    """Mostra i dettagli di un singolo articolo e incrementa le visualizzazioni."""
    article = Article.query.get_or_404(article_id)
    article.views += 1
    db.session.commit()
    return render_template('article_detail.html', article=article)

@app.route('/create', methods=('GET', 'POST'))
@login_required
def create():
    """Permette agli utenti autenticati di creare un nuovo articolo."""
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        image_file = request.files.get('image') # Ottieni il file dall'input 'image'

        if not title or not content:
            flash('Titolo e contenuto sono obbligatori!', 'danger')
            return redirect(url_for('create'))

        image_filename = None
        if image_file and image_file.filename != '': # Controlla se un file è stato effettivamente selezionato
            if allowed_file(image_file.filename):
                original_filename = secure_filename(image_file.filename)
                extension = original_filename.rsplit('.', 1)[1].lower()
                image_filename = str(uuid.uuid4()) + '.' + extension
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
            else:
                flash('Tipo di file immagine non permesso! Sono consentiti solo PNG, JPG, JPEG, GIF.', 'warning')
                return redirect(url_for('create'))


        new_article = Article(title=title, content=content, author=current_user, image_filename=image_filename)
        db.session.add(new_article)
        db.session.commit()
        flash('Articolo creato con successo!', 'success')
        return redirect(url_for('index'))

    return render_template('create.html')

@app.route('/edit/<int:article_id>', methods=('GET', 'POST'))
@login_required
def edit_article(article_id):
    """Permette all'autore o all'admin di modificare un articolo."""
    article = Article.query.get_or_404(article_id)

    # Controllo autorizzazione: solo l'autore o un admin possono modificare
    if article.author != current_user and not current_user.is_admin:
        flash('Non hai il permesso di modificare questo articolo.', 'danger')
        return redirect(url_for('article_detail', article_id=article.id))

    if request.method == 'POST':
        article.title = request.form['title']
        article.content = request.form['content']
        image_file = request.files.get('image')

        if not article.title or not article.content:
            flash('Titolo e contenuto sono obbligatori!', 'danger')
            return redirect(url_for('edit_article', article_id=article.id))

        if image_file and image_file.filename != '':
            if allowed_file(image_file.filename):
                # Elimina la vecchia immagine se presente
                if article.image_filename:
                    old_image_path = os.path.join(app.config['UPLOAD_FOLDER'], article.image_filename)
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                original_filename = secure_filename(image_file.filename)
                extension = original_filename.rsplit('.', 1)[1].lower()
                new_image_filename = str(uuid.uuid4()) + '.' + extension
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_image_filename))
                article.image_filename = new_image_filename
                flash('Nuova immagine caricata con successo!', 'success')
            else:
                flash('Tipo di file immagine non permesso! Sono consentiti solo PNG, JPG, JPEG, GIF.', 'warning')
                return redirect(url_for('edit_article', article_id=article.id))
        
        # Per implementare la rimozione dell'immagine senza caricarne una nuova,
        # si potrebbe aggiungere una checkbox nel form HTML.
        # Es: remove_image = request.form.get('remove_image_checkbox')
        # if remove_image and article.image_filename:
        #    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], article.image_filename))
        #    article.image_filename = None

        db.session.commit()
        flash('Articolo aggiornato con successo!', 'success')
        return redirect(url_for('article_detail', article_id=article.id))

    return render_template('edit_article.html', article=article)


@app.route('/delete/<int:article_id>', methods=('POST',))
@login_required
def delete(article_id):
    """Permette all'autore dell'articolo o all'admin di eliminare un articolo."""
    article_to_delete = Article.query.get_or_404(article_id)
    # L'autore o l'admin possono eliminare l'articolo
    if article_to_delete.author != current_user and not current_user.is_admin:
        flash('Non hai il permesso di eliminare questo articolo!', 'danger')
        return redirect(url_for('index'))

    # Elimina anche il file immagine associato se esiste
    if article_to_delete.image_filename:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], article_to_delete.image_filename)
        if os.path.exists(image_path):
            os.remove(image_path)

    db.session.delete(article_to_delete)
    db.session.commit()
    flash('Articolo eliminato con successo!', 'success')
    return redirect(url_for('index'))


# Rotta per la pagina del profilo utente
@app.route('/user/<string:username>')
def user_profile(username):
    """Mostra il profilo pubblico di un utente e i suoi articoli."""
    user = User.query.filter_by(username=username).first_or_404()
    # Ordina gli articoli dell'utente per data di pubblicazione
    articles = Article.query.filter_by(author=user).order_by(Article.pub_date.desc()).all()
    return render_template('user_profile.html', user=user, articles=articles)

# Rotta per la modifica del profilo utente
@app.route('/edit_profile', methods=('GET', 'POST'))
@login_required
def edit_profile():
    """Permette all'utente corrente di modificare il proprio profilo."""
    user = current_user
    if request.method == 'POST':
        # Validazione base per username ed email (devono essere unici e non quelli di altri utenti)
        new_username = request.form['username']
        new_email = request.form['email']

        # Controllo se il nuovo username è già in uso da un altro utente (escluso se stesso)
        if new_username != user.username and User.query.filter_by(username=new_username).first():
            flash('Username già in uso da un altro utente!', 'danger')
            return redirect(url_for('edit_profile'))
        
        # Controllo se la nuova email è già in uso da un altro utente (escluso se stesso)
        if new_email != user.email and User.query.filter_by(email=new_email).first():
            flash('Email già in uso da un altro utente!', 'danger')
            return redirect(url_for('edit_profile'))

        user.username = new_username
        user.email = new_email
        user.bio = request.form['bio']

        profile_pic_file = request.files.get('profile_picture')
        if profile_pic_file and profile_pic_file.filename != '':
            if allowed_file(profile_pic_file.filename):
                # Elimina la vecchia immagine profilo se presente
                if user.profile_picture:
                    old_pic_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_picture)
                    if os.path.exists(old_pic_path):
                        os.remove(old_pic_path)
                original_filename = secure_filename(profile_pic_file.filename)
                extension = original_filename.rsplit('.', 1)[1].lower()
                new_pic_filename = str(uuid.uuid4()) + '.' + extension
                profile_pic_file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_pic_filename))
                user.profile_picture = new_pic_filename
                flash('Immagine profilo caricata con successo!', 'success')
            else:
                flash('Tipo di file immagine profilo non permesso! Sono consentiti solo PNG, JPG, JPEG, GIF.', 'warning')
                return redirect(url_for('edit_profile'))

        db.session.commit()
        flash('Profilo aggiornato con successo!', 'success')
        return redirect(url_for('user_profile', username=user.username))

    return render_template('edit_profile.html', user=user)

# Rotta per il chatbot AI
@app.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    """Gestisce le interazioni con il chatbot AI."""
    response_text = ""
    if request.method == 'POST':
        user_message = request.form['message']
        if user_message:
            if model: # Controlla se il modello AI è stato caricato con successo
                try:
                    # Invia il messaggio al modello Gemini (una nuova chat per ogni richiesta per semplicità)
                    chat = model.start_chat(history=[])
                    gemini_response = chat.send_message(user_message)
                    response_text = gemini_response.text
                except Exception as e:
                    response_text = f"Errore del chatbot: {e}"
                    flash("Si è verificato un errore con il chatbot. Riprova più tardi.", 'danger')
            else:
                response_text = "Il chatbot AI non è disponibile. Controlla la configurazione del modello o la chiave API."
                flash("Il chatbot AI non è disponibile. Controlla il log del server per maggiori dettagli.", 'danger')
    return render_template('chatbot.html', response_text=response_text)

# Rotta per la gestione degli utenti (solo Admin)
@app.route('/admin/users')
@role_required(role='admin')
def admin_users():
    """Mostra la lista degli utenti per la gestione da parte dell'admin."""
    users = User.query.all()
    return render_template('admin_users.html', users=users)

# Rotta per cambiare il ruolo di un utente (solo Admin)
@app.route('/admin/toggle_admin/<int:user_id>', methods=('POST',))
@role_required(role='admin')
def toggle_admin(user_id):
    """Permette all'admin di abilitare/disabilitare lo stato di amministratore per un utente."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id: # Un utente non può declassare se stesso
        flash("Non puoi modificare il tuo stato di amministratore da qui.", 'warning')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f"Ruolo di amministratore per {user.username} è ora {'abilitato' if user.is_admin else 'disabilitato'}.", 'success')
    return redirect(url_for('admin_users'))

# Rotta per aggiungere un commento
@app.route('/article/<int:article_id>/comment', methods=('POST',))
@login_required
def add_comment(article_id):
    """Permette agli utenti autenticati di aggiungere un commento a un articolo."""
    article = Article.query.get_or_404(article_id)
    comment_text = request.form['comment_text']

    if not comment_text:
        flash('Il commento non può essere vuoto!', 'danger')
    else:
        # Crea il commento usando user_id e article_id
        new_comment = Comment(text=comment_text, user_id=current_user.id, article_id=article.id)
        db.session.add(new_comment)
        db.session.commit()
        flash('Commento aggiunto con successo!', 'success')
    return redirect(url_for('article_detail', article_id=article.id))

# Rotta per eliminare un commento
@app.route('/delete_comment/<int:comment_id>', methods=('POST',))
@login_required
def delete_comment(comment_id):
    """Permette all'autore del commento o all'admin di eliminarlo."""
    comment_to_delete = Comment.query.get_or_404(comment_id)

    # Solo l'autore del commento o un admin può eliminare
    if comment_to_delete.comment_author != current_user and not current_user.is_admin:
        flash('Non hai il permesso di eliminare questo commento!', 'danger')
        return redirect(url_for('article_detail', article_to_delete.article.id))

    article_id = comment_to_delete.article.id # Salva l'ID dell'articolo per il reindirizzamento
    db.session.delete(comment_to_delete)
    db.session.commit()
    flash('Commento eliminato con successo!', 'success')
    return redirect(url_for('article_detail', article_id=article_id))

# Rotta API per gestire i "Mi Piace"
@app.route('/toggle_like/<int:article_id>', methods=['POST'])
@login_required
def toggle_like(article_id):
    """Gestisce l'aggiunta o la rimozione di un "Mi Piace" a un articolo tramite richiesta AJAX."""
    article = Article.query.get_or_404(article_id)
    user_id = current_user.id

    existing_like = Like.query.filter_by(user_id=user_id, article_id=article_id).first()

    if existing_like:
        # Se esiste già un like, rimuovilo (un-like)
        db.session.delete(existing_like)
        db.session.commit()
        return jsonify({'status': 'unliked', 'likes_count': len(article.likes)}) # Restituisce il nuovo conteggio
    else:
        # Se non esiste, aggiungi un like
        new_like = Like(user_id=user_id, article_id=article_id, timestamp=datetime.now())
        db.session.add(new_like)
        db.session.commit()
        return jsonify({'status': 'liked', 'likes_count': len(article.likes)}) # Restituisce il nuovo conteggio

# Rotte di Registrazione, Login, Logout
@app.route('/register', methods=('GET', 'POST'))
def register():
    """Permette la registrazione di nuovi utenti."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        if not username or not email or not password or not confirm_password:
            flash('Tutti i campi sono obbligatori!', 'danger')
            return redirect(url_for('register'))
        if password != confirm_password:
            flash('Le password non corrispondono!', 'danger')
            return redirect(url_for('register'))
        user_by_username = User.query.filter_by(username=username).first()
        user_by_email = User.query.filter_by(email=email).first()
        if user_by_username:
            flash('Username già registrato!', 'danger')
            return redirect(url_for('register'))
        if user_by_email:
            flash('Email già registrata!', 'danger')
            return redirect(url_for('register'))
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registrazione completata con successo! Ora puoi accedere.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=('GET', 'POST'))
def login():
    """Gestisce il login degli utenti."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember_me = request.form.get('remember_me')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(remember_me))
            flash('Accesso effettuato con successo!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Credenziali non valide. Controlla username e password.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Effettua il logout dell'utente corrente."""
    logout_user()
    flash('Disconnesso con successo.', 'info')
    return redirect(url_for('index'))


# --- Avvio dell'Applicazione ---
if __name__ == '__main__':
    # Esegui l'app in modalità debug per lo sviluppo (ricarica automatica e messaggi di errore)
    app.run(debug=True)