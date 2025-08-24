from flask import *
calculator_bp = Blueprint(
    'calculator', 
    __name__,template_folder='../templates')

@calculator_bp.route('/calculator_home')
def calculator_home():
    return render_template('calculator.html')

