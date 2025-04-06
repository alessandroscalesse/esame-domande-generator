from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_session import Session  # <-- Aggiunta importante
import random
import csv
import os
import time
import hashlib
from werkzeug.utils import secure_filename
from math import ceil

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configurazione modificata per le sessioni lato server
app.config.update(
    SESSION_TYPE='filesystem',          # Usa storage su filesystem
    SESSION_FILE_DIR='./flask_session', # Cartella per salvare le sessioni
    SESSION_PERMANENT=False,            # Sessioni non permanenti
    SESSION_USE_SIGNER=True,            # Firma sicura dei cookie
    UPLOAD_FOLDER='uploads',
    ALLOWED_EXTENSIONS={'csv'},
    PERMANENT_SESSION_LIFETIME=3600
)

# Inizializza il sistema di sessioni
Session(app)  # <-- Inizializzazione cruciale

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)  # Crea la cartella per le sessioni


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

class QuizManager:
    def __init__(self):
        self.questions = []
        self.question_map = {}
        self.last_update = 0
        self.load_existing_questions(force=True)
    
    def generate_hash(self, question_text, options):
        return hashlib.sha256(f"{question_text}{''.join(sorted(options))}".encode()).hexdigest()
    
    def load_existing_questions(self, force=False):
        if time.time() - self.last_update < 2 and not force:
            return
            
        self.questions = []
        self.question_map = {}
        upload_dir = app.config['UPLOAD_FOLDER']
        
        for filename in os.listdir(upload_dir):
            if filename.endswith('.csv'):
                filepath = os.path.join(upload_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        required_cols = ['Domanda','Opzione1','Opzione2','Opzione3','Opzione4','Corretta']
                        
                        if not all(col in reader.fieldnames for col in required_cols):
                            continue
                            
                        for row_num, row in enumerate(reader, 1):
                            try:
                                question_text = row['Domanda'].strip()
                                options = [
                                    row['Opzione1'].strip(),
                                    row['Opzione2'].strip(),
                                    row['Opzione3'].strip(),
                                    row['Opzione4'].strip()
                                ]
                                q_hash = self.generate_hash(question_text, options)
                                
                                correct = row['Corretta'].strip().upper()
                                if correct in {'A', 'B', 'C', 'D'}:
                                    correct_num = ord(correct) - ord('A') + 1
                                else:
                                    correct_num = int(correct)
                                
                                if not 1 <= correct_num <= 4:
                                    continue
                                
                                entry = {
                                    'question': question_text,
                                    'options': options,
                                    'correct': correct_num - 1,
                                    'source': filename,
                                    'row': row_num
                                }
                                
                                if q_hash not in self.question_map:
                                    self.question_map[q_hash] = []
                                self.question_map[q_hash].append(entry)
                                
                            except Exception as e:
                                continue
                except Exception as e:
                    print(f"Errore file {filename}: {str(e)}")
        
        for q_hash, entries in self.question_map.items():
            if entries:
                self.questions.append(entries[0])
        
        self.last_update = time.time()
    
    def get_duplicates(self):
        return {h: entries for h, entries in self.question_map.items() if len(entries) > 1}
    
    def remove_duplicates(self, hashes_to_remove):
        removed = 0
        sorted_hashes = sorted(hashes_to_remove, key=lambda h: self.question_map[h][0]['source'])
        
        for q_hash in sorted_hashes:
            if q_hash in self.question_map:
                entries = self.question_map[q_hash]
                if len(entries) > 1:
                    for entry in reversed(entries[1:]):
                        try:
                            self.remove_from_source_file(entry['source'], entry['row'])
                            removed += 1
                        except Exception as e:
                            print(f"Errore rimozione: {str(e)}")
        
        self.load_existing_questions(force=True)
        return removed
    
    def remove_from_source_file(self, filename, row_num):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = list(csv.reader(f))
            header = lines[0]
            rows = lines[1:]
        
        new_rows = [row for i, row in enumerate(rows, 1) if i != row_num]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(new_rows)
    
    def add_question(self, data):
        try:
            question_text = data['question'].strip()
            options = [
                data['option1'].strip(),
                data['option2'].strip(),
                data['option3'].strip(),
                data['option4'].strip()
            ]
            correct_num = int(data['correct'])
            
            if not 1 <= correct_num <= 4:
                raise ValueError("Risposta corretta deve essere 1-4")
            
            q_hash = self.generate_hash(question_text, options)
            
            if q_hash in self.question_map:
                return False
            
            new_question = {
                'question': question_text,
                'options': options,
                'correct': correct_num - 1
            }
            
            self.questions.append(new_question)
            self.question_map[q_hash] = [{
                'question': question_text,
                'options': options,
                'correct': correct_num - 1,
                'source': 'manual.csv',
                'row': len(self.questions)
            }]
            
            self.save_to_csv(new_question, correct_num)
            return True
            
        except Exception as e:
            print(f"Errore aggiunta domanda: {str(e)}")
            return False
    
    def save_to_csv(self, question, correct_num):
        manual_path = os.path.join(app.config['UPLOAD_FOLDER'], 'manual.csv')
        file_exists = os.path.exists(manual_path)
        
        with open(manual_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['Domanda','Opzione1','Opzione2','Opzione3','Opzione4','Corretta'])
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'Domanda': question['question'],
                'Opzione1': question['options'][0],
                'Opzione2': question['options'][1],
                'Opzione3': question['options'][2],
                'Opzione4': question['options'][3],
                'Corretta': correct_num
            })
    
    def update_question_in_source(self, filename, row_num, new_data):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = list(csv.reader(f))
            header = lines[0]
            rows = lines[1:]
        
        updated_row = [
            new_data['question'],
            new_data['option1'],
            new_data['option2'],
            new_data['option3'],
            new_data['option4'],
            new_data['correct']
        ]
        
        if 0 <= row_num - 1 < len(rows):
            rows[row_num - 1] = updated_row
        else:
            raise IndexError("Numero riga non valido")
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        
        self.load_existing_questions(force=True)

quiz_manager = QuizManager()

@app.context_processor
def inject_quiz_manager():
    return dict(quiz_manager=quiz_manager)

@app.template_filter('min')
def min_filter(a, b):
    return min(a, b)

@app.route('/')
def index():
    quiz_manager.load_existing_questions()
    total = len(quiz_manager.questions)
    max_q = (total // 5) * 5 if total >=5 else 0
    return render_template('index.html',
                         question_count=total,
                         max_questions=max_q)

@app.route('/add', methods=['GET', 'POST'])
def add_question():
    if request.method == 'POST':
        try:
            data = {
                'question': request.form['question'],
                'option1': request.form['option1'],
                'option2': request.form['option2'],
                'option3': request.form['option3'],
                'option4': request.form['option4'],
                'correct': int(request.form['correct'])
            }
            if quiz_manager.add_question(data):
                flash('Domanda aggiunta!', 'success')
            else:
                flash('Domanda già esistente!', 'warning')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Errore: {str(e)}', 'error')
    return render_template('add_question.html')

@app.route('/upload', methods=['POST'])
def upload_csv():
    if 'csv_file' not in request.files:
        flash('Nessun file selezionato', 'error')
        return redirect(url_for('index'))
    
    file = request.files['csv_file']
    if file.filename == '':
        flash('Nessun file selezionato', 'error')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        quiz_manager.load_existing_questions(force=True)
        flash('CSV caricato!', 'success')
    else:
        flash('Formato non supportato', 'error')
    
    return redirect(url_for('index'))

@app.route('/reload')
def reload_questions():
    quiz_manager.load_existing_questions(force=True)
    flash('Domande ricaricate!', 'success')
    return redirect(url_for('index'))

@app.route('/duplicates')
def show_duplicates():
    page = request.args.get('page', 1, type=int)
    per_page = int(request.args.get('per_page', 25))
    
    duplicates = quiz_manager.get_duplicates()
    total_duplicates = sum(len(v) for v in duplicates.values()) - len(duplicates)
    
    duplicates_list = list(duplicates.items())
    total_pages = ceil(len(duplicates_list) / per_page) if per_page > 0 else 1
    per_page = min(max(per_page, 10), 100)
    
    start = (page - 1) * per_page
    end = start + per_page
    duplicates_page = duplicates_list[start:end]

    return render_template('duplicates.html', 
                         duplicates=dict(duplicates_page),
                         total_duplicates=total_duplicates,
                         page=page,
                         total_pages=total_pages,
                         per_page=per_page)

@app.route('/remove-duplicates', methods=['POST'])
def remove_duplicates():
    if request.method == 'POST':
        hashes_to_remove = request.form.getlist('duplicate_hash')
        removed_count = quiz_manager.remove_duplicates(hashes_to_remove)
        flash(f"Rimosse {removed_count} domande duplicate!", 'success')
    return redirect(url_for('show_duplicates'))

@app.route('/remove-all-duplicates', methods=['POST'])
def remove_all_duplicates():
    duplicates = quiz_manager.get_duplicates()
    hashes_to_remove = list(duplicates.keys())
    removed_count = quiz_manager.remove_duplicates(hashes_to_remove)
    flash(f"Rimosse {removed_count} domande duplicate in blocco!", 'success')
    return redirect(url_for('show_duplicates'))

@app.route('/questions')
def manage_questions():
    page = request.args.get('page', 1, type=int)
    per_page = int(request.args.get('per_page', 25))
    search_term = request.args.get('search', '').lower()

    quiz_manager.load_existing_questions()
    all_questions = quiz_manager.questions
    
    if search_term:
        all_questions = [q for q in all_questions if search_term in q['question'].lower()]
    
    total_questions = len(all_questions)
    total_pages = ceil(total_questions / per_page) if per_page > 0 else 1
    per_page = min(max(per_page, 10), 100)
    
    start = (page - 1) * per_page
    end = start + per_page
    questions_page = all_questions[start:end]

    return render_template('all_questions.html',
                         questions=questions_page,
                         page=page,
                         total_pages=total_pages,
                         total_questions=total_questions,
                         per_page=per_page,
                         search_term=search_term)

@app.route('/edit-question/<hash_id>', methods=['GET', 'POST'])
def edit_question(hash_id):
    original_entry = None
    for entries in quiz_manager.question_map.values():
        for entry in entries:
            if quiz_manager.generate_hash(entry['question'], entry['options']) == hash_id:
                original_entry = entry
                break
        if original_entry:
            break
    
    if not original_entry:
        flash('Domanda non trovata', 'error')
        return redirect(url_for('manage_questions'))
    
    if request.method == 'POST':
        try:
            new_data = {
                'question': request.form['question'],
                'option1': request.form['option1'],
                'option2': request.form['option2'],
                'option3': request.form['option3'],
                'option4': request.form['option4'],
                'correct': int(request.form['correct']) + 1
            }
            
            quiz_manager.update_question_in_source(
                original_entry['source'],
                original_entry['row'],
                new_data
            )
            
            flash('Domanda aggiornata con successo!', 'success')
            return redirect(url_for('manage_questions'))
        
        except Exception as e:
            flash(f'Errore durante l\'aggiornamento: {str(e)}', 'error')
    
    question_data = {
        'question': original_entry['question'],
        'option1': original_entry['options'][0],
        'option2': original_entry['options'][1],
        'option3': original_entry['options'][2],
        'option4': original_entry['options'][3],
        'correct': original_entry['correct']
    }
    
    return render_template('edit_question.html',
                         question=question_data,
                         hash_id=hash_id)

@app.route('/delete-question/<hash_id>')
def delete_question(hash_id):
    try:
        for entries in quiz_manager.question_map.values():
            for entry in entries:
                if quiz_manager.generate_hash(entry['question'], entry['options']) == hash_id:
                    quiz_manager.remove_from_source_file(entry['source'], entry['row'])
                    flash('Domanda eliminata con successo!', 'success')
                    return redirect(url_for('manage_questions'))
        
        flash('Domanda non trovata', 'error')
    except Exception as e:
        flash(f'Errore durante l\'eliminazione: {str(e)}', 'error')
    
    return redirect(url_for('manage_questions'))

@app.route('/quiz', methods=['POST'])
def start_quiz():
    try:
        num_q = int(request.form['question_count'])
        total = len(quiz_manager.questions)
        
        # Applica il limite massimo di 60 domande
        num_q = min(num_q, 60)
        num_q = max(5, min(num_q, total))
        num_q = (num_q // 5) * 5  # Arrotonda al multiplo di 5 più vicino
        
        session.clear()
        session.update({
            'questions': random.sample(quiz_manager.questions, num_q),
            'score': 0,
            'current': 0,
            'total': num_q,
            'shuffled': []
        })
        session.modified = True
        
        return redirect(url_for('show_quiz'))
    except Exception as e:
        flash(f"Errore: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/quiz/show', methods=['GET', 'POST'])
def show_quiz():
    if 'questions' not in session:
        return redirect(url_for('index'))
    
    try:
        if request.method == 'POST':
            if 'answer' not in request.form:
                flash("Seleziona una risposta!", 'error')
                return redirect(url_for('show_quiz'))
            
            selected = int(request.form['answer'])
            correct_idx = session['shuffled'][session['current']]
            
            if selected == correct_idx:
                session['score'] += 1
            
            session['current'] += 1
            session.modified = True
            
            if session['current'] >= session['total']:
                return redirect(url_for('result'))
        
        current_q = session['questions'][session['current']]
        options = current_q['options'].copy()
        random.shuffle(options)
        correct_idx = options.index(current_q['options'][current_q['correct']])
        
        if len(session['shuffled']) <= session['current']:
            session['shuffled'].append(correct_idx)
        else:
            session['shuffled'][session['current']] = correct_idx
        
        session.modified = True
        
        return render_template('quiz.html',
            question=current_q['question'],
            options=options,
            current=session['current'] + 1,
            total=session['total'])
    except Exception as e:
        print(f"ERRORE: {str(e)}")
        flash("Errore nel quiz, riavvia", 'error')
        return redirect(url_for('index'))

@app.route('/result')
def result():
    if 'score' not in session:
        return redirect(url_for('index'))
    
    score = session['score']
    total = session['total']
    percent = round((score / total) * 100, 2) if total > 0 else 0
    return render_template('result.html',
                         score=score,
                         total=total,
                         percent=percent)

if __name__ == '__main__':
    app.run(host='localhost', port=5000, debug=True)