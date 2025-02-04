import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import create_access_token, JWTManager, get_jwt_identity, jwt_required
from lxml import etree

import celery
from celery import Celery
from celery.result import AsyncResult

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'E:/qfl-codes/qft-task/media'
app.config['ALLOWED_EXTENSIONS'] = {'xml'}

app.config['SECRET_KEY'] = 'secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:201830011@localhost/test_01'

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

db = SQLAlchemy(app)
jwt = JWTManager(app)




def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    celery.Task = ContextTask
    return celery

class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

celery = make_celery(app)




class User(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=True)

class SharePosition(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_code = db.Column(db.Integer, nullable=False)
    security_code = db.Column(db.String(225), nullable=False)
    isin = db.Column(db.String(225), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    position_type = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<Item {self.client_code} - {self.security_code}>'

with app.app_context():
    db.create_all()



os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']



@celery.task
def process_file(filepath):
    try:
        tree = etree.parse(filepath)
        root = tree.getroot()
        for item in root.findall('InsertOne'):
            client_code = int(item.find('ClientCode').text)
            security_code = item.find('SecurityCode').text
            isin = item.find('ISIN').text
            quantity = int(item.find('Quantity').text)
            total_cost = float(item.find('TotalCost').text)
            position_type = item.find('PositionType').text

            new_data = SharePosition(client_code=client_code, security_code=security_code, isin=isin, quantity=quantity, total_cost=total_cost, position_type=position_type)
            db.session.add(new_data)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e

@app.route('/registration', methods=['POST'])
def user_registration():
    data = request.get_json()
    username = data['username']
    password = data['password']

    if not username or not password:
        return jsonify(message="Missing username or password!"), 400

    if User.query.filter_by(username=username).first():
        return jsonify(message="Username already exists!"), 400

    new_user = User(username=username, password=password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify(message="User created successfully"), 201

@app.route('/login', methods=['POST'])
def user_login():
    data = request.get_json()
    username = data['username']
    password = data['password']

    if not username or not password:
        return jsonify(message="Missing username or password!"), 400

    user = User.query.filter_by(username=username).first()
    if user and user.password == password:
        access_token = create_access_token(identity=user.id)
        return jsonify(access_token=access_token), 200

    return jsonify(message="Invalid credentials"), 401



@app.route('/file', methods=['GET', 'POST'])
def user_upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['file']

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = file.filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            result = process_file.delay(filepath)

            flash('File successfully uploaded and data processing started')

            print(f"Task ID: {result.id}")
            return redirect(request.url)

        else:
            flash('File type not allowed')
            return redirect(request.url)

    return render_template('index.html')



@app.route('/task_status/<task_id>', methods=['GET'])
@jwt_required()
def task_status(task_id):
    task = AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'result': task.result
        }
    else:
        response = {
            'state': task.state,
            'result': str(task.info)
        }
    return jsonify(response)



# this use for api
@app.route('/upload', methods=['POST'])
@jwt_required()
def upload_file():
    if 'file' not in request.files:
        return jsonify(error='No file part'), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify(error='No selected file'), 400
    if file and allowed_file(file.filename):
        filename = file.filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        print(filepath)
        file.save(filepath)
        try:
            # Parsing XML and save to database
            tree = etree.parse(filepath)
            root = tree.getroot()
            for item in root.findall('InsertOne'):
                client_code = int(item.find('ClientCode').text)
                security_code = item.find('SecurityCode').text
                isin = item.find('ISIN').text
                quantity = int(item.find('Quantity').text)
                total_cost = float(item.find('TotalCost').text)
                position_type = item.find('PositionType').text

                print(f"{client_code}, {security_code}, {isin}, {quantity}, {total_cost}, {position_type}", end='\n')
                
                new_data = SharePosition(client_code=client_code, security_code=security_code, isin=isin, quantity=quantity, total_cost=total_cost, position_type=position_type)
                db.session.add(new_data)
            
            db.session.commit()
            return jsonify(message='File successfully uploaded and data saved'), 200

        except Exception as e:
            return jsonify(error=str(e)), 500
        
    else:
        return jsonify(error='File type not allowed'), 400


@app.route('/', methods=['GET'])
@jwt_required()
def user_dashboard():
    current_user_id = get_jwt_identity()
    return jsonify(message=f"Hello user {current_user_id}, you accessed the dashboard successfully!"), 200




if __name__ == '__main__':
    app.run(debug=True)
