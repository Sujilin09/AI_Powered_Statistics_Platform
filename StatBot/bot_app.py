from flask import *
import os
import json
import time
import traceback
import uuid
import re
import requests
import platform

# File Processing & AI/ML Libraries
import PyPDF2
import docx
from PIL import Image
import pytesseract
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI

# --- Blueprint Setup ---
# This blueprint will be imported and registered in your main app.py
bot_bp = Blueprint(
    'bot', 
    __name__,
    template_folder='../templates', # Points to the root templates folder
    static_folder='../static'
)

print("[INFO] Loading Sentence Transformer model for Bot...")
sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
print("[SUCCESS] Bot's Sentence Transformer model loaded.")
import os
from dotenv import load_dotenv

# This line loads the variables from your .env file
load_dotenv()

# Now, get the keys using os.getenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

# Use the new uppercase variables to initialize your clients
client = OpenAI(api_key=OPENAI_API_KEY)


# The SERPAPI_KEY is now also set as an environment variable

if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- HELPER FUNCTIONS ---

def get_mysql_connection():
    """Get MySQL connection from the main app"""
    try:
        # The correct way to access the mysql instance from a blueprint
        # Use current_app to get the main app instance, then access mysql
        from flask import current_app
        
        # Check if mysql is available as an attribute
        if hasattr(current_app, 'mysql'):
            return current_app.mysql
        
        # Alternative: Check in extensions
        if hasattr(current_app, 'extensions') and 'mysql' in current_app.extensions:
            return current_app.extensions['mysql']
            
        # If neither works, try to get it from the app's __dict__
        for attr_name in dir(current_app):
            if not attr_name.startswith('_'):
                attr_value = getattr(current_app, attr_name)
                if hasattr(attr_value, 'connection'):  # MySQL objects have a 'connection' attribute
                    return attr_value
        
        raise Exception("MySQL connection not found in current app")
        
    except Exception as e:
        print(f"[ERROR] Failed to get MySQL connection: {e}")
        print(f"[DEBUG] Available app attributes: {[attr for attr in dir(current_app) if not attr.startswith('_')]}")
        if hasattr(current_app, 'extensions'):
            print(f"[DEBUG] Available extensions: {list(current_app.extensions.keys())}")
        raise e

def clean_text_for_database(text):
    """Clean text for database storage"""
    if not text:
        return ""
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8', 'ignore')
        
        # Unicode replacements
        unicode_replacements = {
            '\u2018': "'", '\u2019': "'",
            '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '-',
            '\u2026': '...', '\u2212': '-',
            '\xa0': ' '
        }
        
        for char, replacement in unicode_replacements.items():
            text = text.replace(char, replacement)
        
        # Remove control characters
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        return text.strip()
    except Exception as e:
        print(f"[WARNING] Text cleaning error: {e}")
        return ''.join(char for char in str(text) if ord(char) < 128).strip()

def smart_chunk_text(text, chunk_size=1500, overlap=200, min_chunk_size=100):
    """Smart text chunking with boundary detection"""
    if not text or len(text.strip()) < min_chunk_size:
        return [text.strip()] if text.strip() else []
    
    text = text.strip()
    
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    sentence_endings = ['. ', '! ', '? ']
    paragraph_endings = ['\n\n', '\n']
    
    start = 0
    while start < len(text):
        end = start + chunk_size
        
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk and len(chunk) >= min_chunk_size:
                chunks.append(chunk)
            break
        
        best_break = end
        
        # Look for sentence endings
        search_start = max(start + chunk_size - 300, start)
        search_text = text[search_start:end + 100]
        
        for ending in sentence_endings:
            pos = search_text.rfind(ending)
            if pos != -1:
                best_break = search_start + pos + len(ending)
                break
        
        # If no sentence ending found, look for paragraph breaks
        if best_break == end:
            for ending in paragraph_endings:
                pos = search_text.rfind(ending)
                if pos != -1:
                    best_break = search_start + pos + len(ending)
                    break
        
        chunk = text[start:best_break].strip()
        
        if chunk and len(chunk) >= min_chunk_size:
            chunks.append(chunk)
        
        # Move to next chunk with overlap
        if best_break < len(text):
            next_start = max(best_break - overlap, start + 1)
            start = next_start
        else:
            break
    
    return chunks

def extract_text_from_file(file_path, file_type):
    """Extract text from various file types"""
    try:
        print(f"[DEBUG] Extracting text from: {file_path}, type: {file_type}")
        full_text = ""
        
        if file_type == 'pdf':
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
        
        elif file_type == 'docx':
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                if para.text:
                    full_text += para.text + "\n"
            
            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text:
                            full_text += cell.text + "\n"
        
        elif file_type in ['png', 'jpg', 'jpeg', 'tiff', 'bmp']:
            image = Image.open(file_path)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Try OCR
            extracted_text = pytesseract.image_to_string(image, lang='eng')
            full_text = extracted_text
        
        elif file_type == 'txt':
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as file:
                        full_text = file.read()
                    break
                except UnicodeDecodeError:
                    continue
        
        cleaned_text = clean_text_for_database(full_text)
        
        if not cleaned_text.strip():
            return []
        
        chunks = smart_chunk_text(cleaned_text)
        return chunks
    
    except Exception as e:
        print(f"[ERROR] Text extraction failed: {e}")
        traceback.print_exc()
        return []

def create_embedding(text, model):
    """Create embedding for text"""
    try:
        if not text or len(text.strip()) < 10:
            return None
        
        # Truncate if too long
        if len(text) > 2048:
            text = text[:2048] + "..."
        
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    
    except Exception as e:
        print(f"[ERROR] Embedding creation failed: {e}")
        return None

def process_file_upload(file_path, file_extension, title, filename, mysql_instance, sentence_model, user_id=None):
    try:
        text_chunks = extract_text_from_file(file_path, file_extension)
        if not text_chunks:
            return 0, 0, "Could not extract text or file is empty"
        
        cursor = mysql_instance.connection.cursor()
        successful_chunks = 0
        stored_filename = os.path.basename(file_path)

        for i, chunk in enumerate(text_chunks):
            clean_chunk = clean_text_for_database(chunk)
            if not clean_chunk or len(clean_chunk.strip()) < 50:
                continue
            
            embedding = create_embedding(clean_chunk, sentence_model)
            if embedding is None:
                continue
            
            chunk_title = f"{title}_chunk_{i+1}"
            cursor.execute(
                'INSERT INTO knowledge_base (title, original_filename, content, content_type, embedding, file_path, user_id) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (chunk_title, filename, clean_chunk, file_extension, json.dumps(embedding), stored_filename, user_id)
            )
            successful_chunks += 1
        
        mysql_instance.connection.commit()
        cursor.close()
        return successful_chunks, len(text_chunks), None
    except Exception as e:
        print(f"[ERROR] File processing failed: {e}")
        return 0, 0, f"Processing failed: {str(e)}"

def search_knowledge_base(query, mysql_instance, top_k=5, user_id=None):
    try:
        query_embedding = sentence_model.encode(query)
        cursor = mysql_instance.connection.cursor()
        
        if user_id:
            cursor.execute("SELECT id, content, embedding, original_filename FROM knowledge_base WHERE user_id = %s OR user_id IS NULL", (user_id,))
        else:
            cursor.execute("SELECT id, content, embedding, original_filename FROM knowledge_base")
        
        all_chunks = cursor.fetchall()
        cursor.close()
        
        if not all_chunks: 
            return []
        
        chunk_embeddings = np.array([json.loads(chunk['embedding']) for chunk in all_chunks])
        similarities = cosine_similarity(query_embedding.reshape(1, -1), chunk_embeddings)[0]
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        
        # Add similarity scores to the results
        results = []
        for i in top_indices:
            chunk = dict(all_chunks[i])  # Create a copy
            chunk['similarity'] = float(similarities[i])  # Add similarity score
            results.append(chunk)
        
        return results
        
    except Exception as e:
        print(f"[ERROR] KB search failed: {e}")
        return []

def generate_advanced_response(context, query, source_description="general knowledge"):
    """Generate response using LLM (OpenAI)"""
    print(f"[INFO] Generating response using source: {source_description}")

    system_message = (
        "You are a helpful and precise statistical assistant. "
        "Be concise and format mathematical formulas using LaTeX within single dollar signs (e.g., $E=mc^2$)."
    )
    
    if context:
        user_message = f"Use the following context to answer my question.\n\nCONTEXT:\n---\n{context}\n---\n\nQUESTION: {query}"
    else:
        user_message = query

    try:
        print(f"[DEBUG] Making OpenAI API call...")
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        
        result = response.choices[0].message.content.strip()
        print(f"[SUCCESS] OpenAI response generated successfully")
        return result
        
    except Exception as e:
        print(f"[ERROR] OpenAI LLM generation failed: {e}")
        traceback.print_exc()
        return f"Sorry, I encountered an error while generating a response. Please try again later."

def web_search(query):
    """Perform web search using SerpAPI"""
    if not SERPAPI_KEY or 'your_serpapi_key' in SERPAPI_KEY:
        print("[WARNING] SerpAPI key not configured. Skipping web search.")
        return []

    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": "us",
        "hl": "en"
    }
    
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=10)
        response.raise_for_status()
        results = response.json()
        
        if "organic_results" in results and results["organic_results"]:
            return [{
                "title": res.get("title", "No Title"),
                "link": res.get("link", "#"),
                "snippet": res.get("snippet", "No snippet available.")
            } for res in results["organic_results"]]
        return []
    except Exception as e:
        print(f"[ERROR] SerpAPI request failed: {e}")
        return []

def check_for_mathematical_content(text):
    """Check if text contains mathematical formulas"""
    math_indicators = [
        '=', '±', '≠', '≤', '≥', '∑', '√', 'σ', 'μ', 'x̄', 'α', 'β', 'χ²',
        'H0:', 'H1:', 'df =', '∙', '²', '÷', '∈', '∫', '∞', '$'
    ]
    return any(indicator in text for indicator in math_indicators)

def enhance_mathematical_content(text):
    """Enhance mathematical formulas for better display"""
    replacements = {
        '±': ' ± ', '≠': ' ≠ ', '≤': ' ≤ ', '≥': ' ≥ ', '∙': ' · ',
        'x̄': 'x̄', 'σ²': 'σ²', 'χ²': 'χ²', 'H0:': 'H₀:', 'H1:': 'H₁:',
        'μ0': 'μ₀', 'p0': 'p₀', 'μ1': 'μ₁', 'μ2': 'μ₂', 'p1': 'p₁',
        'p2': 'p₂', 'α/2': 'α/2', 'zα/2': 'zα/2', 't α/2': 'tα/2',
        'df': 'df', '= ': ' = ', ' =': ' = ',
    }
    
    enhanced_text = text
    for old, new in replacements.items():
        enhanced_text = enhanced_text.replace(old, new)

    return enhanced_text

# --- Bot Routes ---
# Note the use of @bot_bp.route instead of @app.route

@bot_bp.route('/')
def bot_home():
    """Renders the main chatbot interface page."""
    if not session.get('loggedin'):
        return redirect('/')
    return render_template('bot.html', user_name=session.get('user_name'))

@bot_bp.route('/upload', methods=['POST'])
def upload_file():
    """Handle file uploads"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in request'}), 400
            
        file = request.files['file']
        
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        title = request.form.get('title', file.filename)
        user_id = session.get('user_id')
        
        file_extension = file.filename.split('.')[-1].lower()
        supported_types = ['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg', 'tiff', 'bmp']
        
        if file_extension not in supported_types:
            return jsonify({
                'error': f'Unsupported file type: {file_extension}',
                'supported_types': supported_types
            }), 400
        
        uploads_dir = 'uploads'
        os.makedirs(uploads_dir, exist_ok=True)
        
        unique_filename = f"{int(time.time())}_{file.filename}"
        file_path = os.path.join(uploads_dir, unique_filename)
        file.save(file_path)
        
        successful_chunks, total_chunks, error = process_file_upload(
            file_path, file_extension, title, file.filename, mysql, sentence_model, user_id
        )
        
        if error:
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'error': error}), 500
        
        if successful_chunks == 0:
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'error': 'Failed to process any chunks from the file'}), 500
        
        return jsonify({
            'message': f'File "{file.filename}" processed successfully!',
            'chunks_count': successful_chunks,
            'total_chunks': total_chunks,
            'filename': file.filename
        })
    
    except Exception as e:
        print(f"[ERROR] Upload error: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@bot_bp.route('/chat', methods=['POST'])
def chat():
    """Handle chat requests with RAG -> Web Search -> LLM fallback"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        data = request.json
        query = data.get('message', '').strip()
        session_id = data.get('session_id', str(uuid.uuid4()))
        user_id = session.get('user_id')
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        print(f"[DEBUG] Processing query: '{query}' for user: {user_id}")
        
        context, source_type, source_info, source_documents = "", "llm", "General Knowledge", []
        
        # Step 1: Search Knowledge Base (RAG) - user-specific first
        kb_results = search_knowledge_base(query, mysql, top_k=3, user_id=user_id)
        
        if kb_results and kb_results[0]['similarity'] > 0.3:  # Use similarity threshold
            context = "\n\n".join([chunk['content'] for chunk in kb_results])
            source_type = 'rag'
            unique_sources = list(set([chunk['original_filename'] for chunk in kb_results]))
            source_info = f"Sources: {', '.join(unique_sources)}"
            source_documents = kb_results
        
        # Step 2: Fallback to Web Search
        if not context:
            search_results = web_search(query)
            if search_results:
                context = "\n\n".join([f"{res['title']}: {res['snippet']}" for res in search_results[:3]])
                source_type = 'web_search'
                source_info = "Web Search Results"
                source_documents = search_results[:3]

        # Step 3: Generate Response
        response_text = generate_advanced_response(context, query, source_info)

        # Step 4: Save conversation
        try:
            cursor = mysql.connection.cursor()
            cursor.execute(
                "INSERT INTO conversations (session_id, user_query, bot_response, source_type, source_documents, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (session_id, query, response_text, source_type, json.dumps(source_documents), user_id)
            )
            mysql.connection.commit()
            cursor.close()
        except Exception as e:
            print(f"[ERROR] Error storing conversation: {e}")
        
        return jsonify({
            'reply': response_text,
            'source_type': source_type,
            'source_info': source_info,
            'source_documents': source_documents
        })
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bot_bp.route('/knowledge-base')
def get_knowledge_base():
    """Get knowledge base entries for current user"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        user_id = session.get('user_id')
        cursor = mysql.connection.cursor()
        
        # Get user-specific documents
        cursor.execute('''
            SELECT original_filename, content_type, COUNT(*) as chunks_count, MIN(created_at) as first_uploaded
            FROM knowledge_base
            WHERE user_id = %s
            GROUP BY original_filename, content_type
            ORDER BY first_uploaded DESC
        ''', (user_id,))
        entries = cursor.fetchall()
        cursor.close()
        
        for entry in entries:
            entry['created_at'] = entry['first_uploaded'].strftime("%Y-%m-%d %H:%M:%S")
            entry['title'] = entry['original_filename']
        
        return jsonify({'entries': entries})
    except Exception as e:
        print(f"[ERROR] Knowledge base retrieval error: {e}")
        return jsonify({'error': str(e)}), 500

@bot_bp.route('/document-content', methods=['POST'])
def get_document_content():
    """Get document content (summary or full) for current user"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        data = request.json
        filename = data.get('filename', '').strip()
        view_type = data.get('view_type', 'summary').strip()
        user_id = session.get('user_id')
        
        if not filename:
            return jsonify({'error': 'Filename is required'}), 400
        
        cursor = mysql.connection.cursor()
        cursor.execute('''
            SELECT content, created_at, file_path
            FROM knowledge_base 
            WHERE original_filename = %s AND user_id = %s
            ORDER BY title ASC
        ''', (filename, user_id))
        chunks = cursor.fetchall()
        cursor.close()
        
        if not chunks:
            return jsonify({'error': f'Document "{filename}" not found in your knowledge base'}), 404
        
        # Combine all chunks
        full_content = "\n\n".join([chunk['content'] for chunk in chunks])
        
        if view_type == 'summary':
            # Generate summary using OpenAI
            prompt = f"Summarize the following document content concisely, highlighting key statistical formulas and concepts:\n\n{full_content[:3000]}..."
            
            try:
                summary_content = generate_advanced_response("", prompt, "document summary")
            except Exception as e:
                print(f"[ERROR] Summary generation failed: {e}")
                summary_content = "Failed to generate summary. The full document is available."
            
            return jsonify({
                'content': summary_content,
                'view_type': 'summary',
                'filename': filename,
                'total_chunks': len(chunks),
                'total_length': len(full_content),
                'has_math': check_for_mathematical_content(summary_content)
            })
        
        # For 'full' view
        has_math = check_for_mathematical_content(full_content)
        if has_math:
            full_content = enhance_mathematical_content(full_content)
        
        return jsonify({
            'content': full_content,
            'view_type': 'full',
            'filename': filename,
            'total_chunks': len(chunks),
            'total_length': len(full_content),
            'has_math': has_math
        })
    
    except Exception as e:
        print(f"[ERROR] Document content retrieval error: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to retrieve document content: {str(e)}'}), 500

@bot_bp.route('/history/<session_id>')
def get_history(session_id):
    """Get conversation history for current user"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        user_id = session.get('user_id')
        cursor = mysql.connection.cursor()
        cursor.execute('''
            SELECT user_query, bot_response, source_type, source_documents, created_at 
            FROM conversations 
            WHERE session_id = %s AND user_id = %s
            ORDER BY created_at DESC 
            LIMIT 20
        ''', (session_id, user_id))
        
        history = cursor.fetchall()
        cursor.close()
        
        formatted_history = []
        for item in history:
            formatted_history.append({
                'user_query': item['user_query'],
                'bot_response': item['bot_response'],
                'source_type': item['source_type'],
                'source_documents': json.loads(item['source_documents']) if item['source_documents'] else [],
                'created_at': item['created_at'].strftime("%Y-%m-%d %H:%M:%S")
            })
        
        return jsonify({'history': formatted_history})
    
    except Exception as e:
        print(f"History retrieval error: {e}")
        return jsonify({'error': str(e)}), 500

@bot_bp.route('/original-document/<path:filename>')
def get_original_document(filename):
    """Serve original documents with proper headers for current user"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        user_id = session.get('user_id')
        
        # Verify user owns this document
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT file_path FROM knowledge_base WHERE original_filename = %s AND user_id = %s LIMIT 1', 
                      (filename, user_id))
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            return jsonify({'error': 'Document not found or access denied'}), 404
        
        stored_filename = result['file_path']
        uploads_dir = os.path.abspath('uploads')
        file_path = os.path.join(uploads_dir, stored_filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Document file not found'}), 404
        
        file_extension = filename.split('.')[-1].lower()
        
        content_type_map = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'txt': 'text/plain',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'tiff': 'image/tiff',
            'bmp': 'image/bmp'
        }
        
        if file_extension == 'pdf':
            response = send_from_directory(
                uploads_dir, 
                stored_filename, 
                mimetype='application/pdf'
            )
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
        else:
            return send_from_directory(
                uploads_dir, 
                stored_filename,
                mimetype=content_type_map.get(file_extension, 'application/octet-stream')
            )
            
    except Exception as e:
        print(f"[ERROR] Document serving error: {e}")
        return jsonify({'error': 'Document not found'}), 404

@bot_bp.route('/get-file-info/<path:filename>')
def get_file_info(filename):
    """Get file information for current user"""
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        mysql = get_mysql_connection()
        
        user_id = session.get('user_id')
        cursor = mysql.connection.cursor()
        cursor.execute('''
            SELECT DISTINCT original_filename, file_path, content_type, created_at
            FROM knowledge_base 
            WHERE original_filename = %s AND user_id = %s
            LIMIT 1
        ''', (filename, user_id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            return jsonify({'error': 'File not found in your knowledge base'}), 404
        
        return jsonify({
            'original_filename': result['original_filename'],
            'stored_filename': result['file_path'],
            'content_type': result['content_type'],
            'uploaded_at': result['created_at'].strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        print(f"[ERROR] File info error: {e}")
        return jsonify({'error': str(e)}), 500

# --- TESTING ROUTES ---

@bot_bp.route('/test-db')
def test_database():
    """Test database connection"""
    try:
        mysql = get_mysql_connection()
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT 1")
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        table_info = {}
        for table in tables:
            table_name = list(table.values())[0]
            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            count = cursor.fetchone()['count']
            table_info[table_name] = count
        
        cursor.close()
        
        return jsonify({
            'status': 'Database connection successful',
            'tables': table_info
        })
    
    except Exception as e:
        return jsonify({'error': f'Database test failed: {str(e)}'}), 500

@bot_bp.route('/test-openai')
def test_openai():
    """Test OpenAI API endpoint"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "Say 'Hello, I am working!' in exactly those words."}
            ],
            max_tokens=50
        )
        
        result = response.choices[0].message.content.strip()
        
        return jsonify({
            'status': 'success',
            'message': 'OpenAI API is working correctly',
            'response': result
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'OpenAI API test failed: {str(e)}'
        }), 500

@bot_bp.route('/debug-extensions')
def debug_extensions():
    """Debug route to check what extensions are available"""
    try:
        extensions = list(current_app.extensions.keys()) if hasattr(current_app, 'extensions') else []
        app_attrs = [attr for attr in dir(current_app) if not attr.startswith('_')]
        
        return jsonify({
            'available_extensions': extensions,
            'has_mysql': 'mysql' in extensions if extensions else False,
            'app_config_keys': list(current_app.config.keys()),
            'app_attributes': app_attrs,
            'mysql_found': hasattr(current_app, 'mysql')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500