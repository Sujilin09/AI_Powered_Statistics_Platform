import fitz  # PyMuPDF
import spacy
import random
from sklearn.feature_extraction.text import TfidfVectorizer
import re
import cohere
from collections import Counter
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize
import io
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ------------------- Setup -------------------
def setup_nltk():
    try:
        nltk.data.find('tokenizers/punkt')
        nltk.data.find('corpora/stopwords')
    except LookupError:
        print("Downloading required NLTK data...")
        nltk.download('punkt')
        nltk.download('stopwords')

def load_spacy_model():
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        print("Error: spaCy model 'en_core_web_sm' not found. Install: python -m spacy download en_core_web_sm")
        return None

def setup_cohere():
    api_key = os.getenv('COHERE_API_KEY')
    if not api_key:
        print("Warning: COHERE_API_KEY not found in environment variables")
        return None
    try:
        return cohere.Client(api_key)
    except Exception as e:
        print(f"Error setting up Cohere: {e}")
        return None

setup_nltk()
nlp = load_spacy_model()

# ------------------- PDF Extraction -------------------
def extract_text_from_pdf_advanced(file_path_or_bytes):
    try:
        pdf = fitz.open(file_path_or_bytes) if isinstance(file_path_or_bytes, str) else fitz.open(stream=file_path_or_bytes.read(), filetype="pdf")
        pages_data = []

        for page_num in range(len(pdf)):
            page = pdf[page_num]
            try:
                blocks = page.get_text("dict")
            except:
                page_text = page.get_text()
                pages_data.append({'page_num': page_num + 1, 'text': page_text, 'blocks': [page_text]})
                continue

            text_blocks = []
            for block in blocks.get("blocks", []):
                if "lines" in block:
                    block_text = " ".join(["".join([span.get("text","") for span in line["spans"]]) for line in block["lines"]])
                    if is_main_content(block.get("bbox",[0,0,100,100]), page.rect, block_text):
                        text_blocks.append(block_text.strip())
            page_text = " ".join(text_blocks)
            pages_data.append({'page_num': page_num + 1, 'text': page_text, 'blocks': text_blocks})
        
        pdf.close()
        return pages_data
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return []

def is_main_content(bbox, page_rect, text):
    try:
        x0, y0, x1, y1 = bbox
        page_width, page_height = page_rect.width, page_rect.height
        margin_threshold = 50
        if (y0 < margin_threshold or y1 > page_height - margin_threshold or x0 < margin_threshold or x1 > page_width - margin_threshold):
            if len(text.split()) < 5: return False
        if re.match(r'^\s*\d+\s*$', text.strip()): return False
        if len(text.split()) < 3: return False
        skip_patterns = [r'^chapter\s+\d+', r'^section\s+\d+', r'^figure\s+\d+', r'^table\s+\d+', r'^index$', r'^bibliography$', r'^references$', r'^contents$', r'^appendix', r'^\d+\.\d+\s*$', r'^page\s+\d+']
        text_lower = text.lower().strip()
        for pattern in skip_patterns:
            if re.match(pattern, text_lower): return False
        return True
    except:
        return True

def clean_and_filter_content(pages_data):
    all_text = ""
    content_sections = []
    for page_data in pages_data:
        page_text = page_data['text']
        if is_content_page(page_text):
            cleaned_text = clean_text(page_text)
            if cleaned_text:
                all_text += cleaned_text + "\n"
                content_sections.append({'page': page_data['page_num'], 'text': cleaned_text})
    return all_text, content_sections

def is_content_page(text):
    text_lower = text.lower()
    word_count = len(text.split())
    if word_count < 50: return False
    toc_indicators = ['contents', 'chapter', 'section', '...', '….']
    if any(ind in text_lower for ind in toc_indicators) and word_count < 200: return False
    if 'index' in text_lower and word_count < 300: return False
    ref_indicators = ['references', 'bibliography', 'works cited', 'sources']
    if any(ind in text_lower for ind in ref_indicators): return False
    numbers = re.findall(r'\d+', text)
    if len(numbers)/word_count > 0.1: return False
    return True

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^\d+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\d+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\(see figure \d+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(see table \d+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'figure \d+:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'table \d+:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'http[s]?://\S+', '', text)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', text)
    return text.strip()

def extract_quality_sentences(text, min_length=10, max_length=200):
    if not nlp:
        sentences = sent_tokenize(text)
        return [s for s in sentences if min_length <= len(s.split()) <= max_length]
    doc = nlp(text)
    quality_sentences = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if not (min_length <= len(sent_text.split()) <= max_length): continue
        if len(re.findall(r'\d+', sent_text)) > 3: continue
        if len(re.sub(r'[^a-zA-Z\s]', '', sent_text)) < len(sent_text) * 0.7: continue
        if has_quiz_worthy_content(sent):
            quality_sentences.append(sent_text)
    return quality_sentences

def has_quiz_worthy_content(sent):
    if not nlp: return True
    important_pos = ['NOUN', 'PROPN', 'ADJ']
    named_entities = [ent.label_ for ent in sent.ents]
    important_words = [token for token in sent if token.pos_ in important_pos and not token.is_stop]
    if len(important_words) < 2: return False
    important_entities = ['PERSON', 'ORG', 'GPE', 'DATE', 'EVENT', 'LAW', 'LANGUAGE']
    if any(label in named_entities for label in important_entities): return True
    if len(important_words) >= 3: return True
    return False

# ------------------- MCQ Generation -------------------
def generate_mcqs_from_textbook(file_input, num_questions=5):
    pages_data = extract_text_from_pdf_advanced(file_input)
    if not pages_data: return {"error": "Failed to extract text from PDF"}
    all_text, content_sections = clean_and_filter_content(pages_data)
    if not all_text.strip(): return {"error": "No suitable content found for quiz generation"}
    sentences = extract_quality_sentences(all_text)
    if len(sentences) < num_questions: print(f"Warning: Only found {len(sentences)} suitable sentences for quiz generation")
    questions = generate_advanced_mcqs(sentences, num_questions)
    return {
        "questions": questions,
        "content_pages": len([p for p in pages_data if is_content_page(p['text'])]),
        "total_pages": len(pages_data),
        "sentences_found": len(sentences),
        "success": True
    }

# --- Advanced MCQ generation using TF-IDF ---
def generate_advanced_mcqs(sentences, num_questions):
    if not sentences: return []
    vectorizer = TfidfVectorizer(stop_words='english', max_features=200, ngram_range=(1,2), min_df=2)
    try:
        X = vectorizer.fit_transform(sentences)
        feature_names = vectorizer.get_feature_names_out()
        tfidf_scores = X.toarray()
        questions, used_sentences = [], set()
        for i in range(min(num_questions, len(sentences))):
            best_sentence_idx = find_best_sentence(sentences, tfidf_scores, feature_names, used_sentences)
            if best_sentence_idx is None: break
            sent = sentences[best_sentence_idx]
            used_sentences.add(best_sentence_idx)
            keyword = select_best_keyword(sent, feature_names, tfidf_scores[best_sentence_idx])
            if not keyword: continue
            question_text = re.sub(r'\b'+re.escape(keyword)+r'\b',"_____", sent, flags=re.IGNORECASE)
            distractors = generate_smart_distractors(keyword, feature_names, sent)
            if len(distractors)>=3:
                options = distractors[:3]+[keyword]
                random.shuffle(options)
                correct_index = options.index(keyword)
                answer_letter = chr(65+correct_index)
                questions.append({"question": question_text, "options": options, "answer": keyword, "answer_letter": answer_letter, "source_sentence": sent})
        return questions
    except:
        return generate_simple_mcqs(sentences, num_questions)

def find_best_sentence(sentences, tfidf_scores, feature_names, used_sentences):
    best_score, best_idx = 0, None
    for idx, sent in enumerate(sentences):
        if idx in used_sentences: continue
        sent_score = sum(tfidf_scores[idx])
        if sent_score>best_score: best_score, best_idx = sent_score, idx
    return best_idx

def select_best_keyword(sentence, feature_names, tfidf_scores):
    if not nlp:
        words = sentence.split()
        for i, feature in enumerate(feature_names):
            if feature in sentence.lower() and tfidf_scores[i]>0 and len(feature)>4: return feature
        return None
    doc = nlp(sentence)
    candidates = []
    for i, feature in enumerate(feature_names):
        if feature in sentence.lower() and tfidf_scores[i]>0:
            for token in doc:
                if token.lemma_.lower() == feature.lower():
                    if token.pos_ in ['NOUN','PROPN']: candidates.append((feature, tfidf_scores[i],3))
                    elif token.pos_ in ['ADJ','VERB']: candidates.append((feature, tfidf_scores[i],2))
                    else: candidates.append((feature, tfidf_scores[i],1))
    if not candidates: return None
    candidates.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return candidates[0][0]

def generate_smart_distractors(correct_answer, all_features, sentence):
    if not nlp:
        distractors = [f for f in all_features if f != correct_answer.lower() and len(f) >3]
        return random.sample(distractors, min(3,len(distractors)))
    doc = nlp(sentence)
    correct_doc = nlp(correct_answer)
    target_pos=None
    for token in correct_doc:
        if not token.is_stop: target_pos=token.pos_; break
    distractors=[]
    for feature in all_features:
        if feature!=correct_answer.lower():
            feature_doc = nlp(feature)
            for token in feature_doc:
                if token.pos_==target_pos and len(distractors)<10: distractors.append(feature); break
    remaining_features = [f for f in all_features if f != correct_answer.lower() and f not in distractors]
    while len(distractors)<10 and remaining_features: distractors.append(remaining_features.pop(0))
    return random.sample(distractors,min(3,len(distractors))) if distractors else ["option1","option2","option3"]

def generate_simple_mcqs(sentences, num_questions):
    questions=[]
    stop_words=set(stopwords.words('english'))
    for i in range(min(num_questions,len(sentences))):
        sentence=sentences[i]
        if nlp:
            doc=nlp(sentence)
            nouns=[token.text for token in doc if token.pos_ in ['NOUN','PROPN'] and not token.is_stop]
        else:
            words=word_tokenize(sentence.lower())
            nouns=[w for w in words if w.isalpha() and w not in stop_words and len(w)>3]
        if nouns:
            keyword=random.choice(nouns)
            question=sentence.replace(keyword,"_____")
            distractors=random.sample([n for n in nouns if n!=keyword],3) if len(nouns)>=4 else ["option1","option2","option3"]
            options=distractors+[keyword]; random.shuffle(options)
            correct_index=options.index(keyword)
            answer_letter=chr(65+correct_index)
            questions.append({"question":question,"options":options,"answer":keyword,"answer_letter":answer_letter,"source_sentence":sentence})
    return questions

# ------------------- Cohere Prompt-based -------------------
def generate_questions_from_prompt(prompt, num_questions=5):
    co = setup_cohere()
    if not co: return {"error":"Cohere client not configured. Check API key.","questions":[]}
    try:
        full_prompt = (
            f"Generate exactly {num_questions} multiple choice questions on the topic: '{prompt}'.\n"
            "Each question must have exactly 4 options (A, B, C, D).\n"
            "Strictly follow this format:\n"
            "1. Question text?\n"
            "A. Option 1\n"
            "B. Option 2\n"
            "C. Option 3\n"
            "D. Option 4\n"
            "Answer: B"
        )
        response=co.generate(model="command-r-plus", prompt=full_prompt, max_tokens=1500, temperature=0.6)
        if response.generations:
            generated_text=response.generations[0].text
            print("Raw Cohere output:\n", generated_text)
            parsed=parse_questions(generated_text)
            return {"questions": parsed}
        return {"error":"Cohere API returned no response.","questions":[]}
    except Exception as e:
        print(f"Cohere API error: {e}")
        return {"error":f"An error occurred with the AI model: {e}","questions":[]}

def parse_questions(text):
    question_blocks=re.split(r'\n(?=\d+\.)', text)
    questions=[]
    for block in question_blocks:
        match = re.search(
            r'^\d+\.\s*(?P<question>.*?)\s*\n'
            r'A\.\s*(?P<optA>.*?)\s*\n'
            r'B\.\s*(?P<optB>.*?)\s*\n'
            r'C\.\s*(?P<optC>.*?)\s*\n'
            r'D\.\s*(?P<optD>.*?)\s*\n'
            r'Answer:\s*(?P<answer_letter>[A-D])',
            block,
            re.DOTALL|re.IGNORECASE|re.MULTILINE
        )
        if match:
            data=match.groupdict()
            q_text=data['question'].strip()
            opts=[data['optA'].strip(), data['optB'].strip(), data['optC'].strip(), data['optD'].strip()]
            ans_letter=data['answer_letter'].strip().upper()
            try: correct_answer_text=opts[ord(ans_letter)-ord('A')]
            except: continue
            questions.append({"question":q_text,"options":opts,"answer":correct_answer_text,"answer_letter":ans_letter})
    return questions

# ------------------- Utility -------------------
def print_quiz(questions):
    if not questions: print("No questions generated."); return
    print("="*50+"\nGENERATED QUIZ\n"+"="*50)
    for i,q in enumerate(questions,1):
        print(f"\n{i}. {q['question']}")
        for j,opt in enumerate(q['options']): print(f"   {chr(65+j)}. {opt}")
        print(f"   Answer: {q.get('answer_letter','N/A')} ({q['answer']})")

def test_installation():
    print("Testing packages...")
    try: import fitz; print("✓ PyMuPDF installed")
    except: print("✗ PyMuPDF not installed")
    try: from dotenv import load_dotenv; print("✓ dotenv installed")
    except: print("✗ dotenv not installed")
    try: import spacy; nlp_test=spacy.load("en_core_web_sm"); print("✓ spaCy and model installed")
    except: print("✗ spaCy or model not installed")
