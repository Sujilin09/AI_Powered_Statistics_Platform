# analyzer/analyzer.py

from flask import *
import pandas as pd
import os
from werkzeug.utils import secure_filename
from .analysis import *
import uuid
from flask_mysqldb import MySQL
from flask import send_from_directory, abort
analyzer_bp = Blueprint('analyzer', __name__, template_folder='../templates')

UPLOAD_FOLDER = 'uploads'
REPORT_FOLDER = 'static/reports'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '##Ss090503##'
app.config['MYSQL_DB'] = 'stat_analyser'

mysql=MySQL(app)



@analyzer_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        file = request.files['dataset']
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)

            try:
                if filename.endswith('.csv'):
                    df = pd.read_csv(filepath)
                elif filename.endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(filepath)
                else:
                    flash('Unsupported file type', 'danger')
                    return redirect(url_for('analyzer.dashboard'))

                session['filename'] = filename
                # session['data'] = df.to_json()  # store as JSON string
                # Save the file path only
                session['filepath'] = filepath

                column_types = {}
                for col in df.columns:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        column_types[col] = "number"
                    else:
                        column_types[col] = "object"


                return render_template('dashboard_analyzer.html',
                    email=session.get('email'),
                    columns=df.columns.tolist(),
                    column_types=column_types)  # ✅ send real values



            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'danger')
                return redirect(url_for('analyzer.dashboard'))

    return render_template(
    'dashboard_analyzer.html',
    email=session.get('email'),
    columns=None,
    column_types=None
)



@analyzer_bp.route('/analyze', methods=['POST'])
def analyze():
    print("Analyzing started...")
    print("Session filename:", session.get('filename'))

    if 'filename' not in session or 'filepath' not in session:
        flash('Please upload a dataset first.', 'warning')
        return redirect(url_for('analyzer.dashboard'))

    filename = session.get('filename')
    filepath = session.get('filepath')

    # Load the dataset
    if filename.endswith('.csv'):
        df = pd.read_csv(filepath)
    elif filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(filepath)
    else:
        flash("Unsupported file type.", "danger")
        return redirect(url_for('analyzer.dashboard'))

    task = request.form['task']
    doc = None
    plots = []
    doc_path = None
    report_path = None

    result = {
        'summary_html': "",
        'objective': "",
        'interpretation': "",
        'plots': [],
        'doc': None,
        'preprocessing_steps': "",
        'dataset_description': ""
    }

    if task == 'eda':
        result_html, doc, plots = perform_eda(df)
        result['summary_html'] = result_html
        result['doc'] = doc
        result['plots'] = plots

    elif task == 'simple_regression':
        x_col = request.form['input_column']
        y_col = request.form['output_column']
        result = simple_regression(df, x_col, y_col)
        doc_path = save_docx(result['doc'])  # Save docx and get relative path
        report_path = doc_path  # already relative to 'static/' folder

    elif task == 'multiple_regression':
        x_cols = request.form.getlist('input_columns')
        y_col = request.form['output_column']
        result= multiple_regression(df, x_cols, y_col)
        doc_path=save_docx(result['doc'])
        report_path=doc_path

    elif task == 'one_sample_ttest':
        col = request.form['column']
        result_html, doc = hypothesis_testing(df, col)
        result['summary_html'] = result_html
        result['doc'] = doc

    else:
        result['summary_html'] = "<p>Unsupported task.</p>"

    # Save user activity
    cursor = mysql.connection.cursor()
    cursor.execute(
        'INSERT INTO user_activity (user_id, filename, analysis_type, report_path) VALUES (%s, %s, %s, %s)',
        (session.get('user_id'), filename, task, report_path)
    )
    mysql.connection.commit()

    print("SUMMARY:", result['summary_html'])
    print("OBJECTIVE:", result['objective'])
    print("INTERPRETATION:", result['interpretation'])
    print("PLOTS:", result['plots'])
    print("DOC PATH:", doc_path)

    # ✅ Return template with all values (FIXED the syntax issue with comma)
    return render_template(
        'dashboard_analyzer.html',
        email=session.get('email'),
        columns=df.columns.tolist(),
        summary_table=result['summary_html'],
        objective=result['objective'],
        interpretation=result['interpretation'],
        plots=result['plots'],
        docx_link=doc_path,
        preprocessing_steps=result['preprocessing_steps'],
        dataset_description=result['dataset_description']
    )


def save_docx(doc, folder='static/reports'):
    os.makedirs(folder, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.docx"
    path = os.path.join(folder, filename)
    doc.save(path)
    return filename
# Download .docx Report


@analyzer_bp.route('/download_report/<filename>')
def download_report(filename):
    try:
        # reports folder should be in your project root
        return send_from_directory("reports", filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)


# History placeholder (we’ll improve this later)
@analyzer_bp.route('/history')
def history():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    cursor =mysql.connection.cursor()  
    cursor.execute(
    'SELECT filename, analysis_type, timestamp, report_path FROM user_activity WHERE user_id = %s ORDER BY timestamp DESC',
    (session.get('user_id'),)
)

    history_data = cursor.fetchall()

    return render_template('history.html', history=history_data, name=session.get('user_name'))
