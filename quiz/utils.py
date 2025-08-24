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


# Download required NLTK data (run once)
# nltk.download('punkt')
# nltk.download('stopwords')

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

# Cohere client setup
co = cohere.Client("Cohere_API_KEY")

def extract_text_from_pdf_advanced(file_storage):
    """Enhanced PDF text extraction for textbooks"""
    pdf = fitz.open(stream=file_storage.read(), filetype="pdf")
    
    # Store text with metadata
    pages_data = []
    
    for page_num in range(len(pdf)):
        page = pdf[page_num]
        
        # Get text blocks with position information
        blocks = page.get_text("dict")
        
        # Extract text while preserving some layout info
        page_text = ""
        text_blocks = []
        
        for block in blocks["blocks"]:
            if "lines" in block:  # Text block
                block_text = ""
                for line in block["lines"]:
                    line_text = ""
                    for span in line["spans"]:
                        line_text += span["text"]
                    block_text += line_text + " "
                
                # Filter out likely headers/footers based on position and font size
                bbox = block["bbox"]
                if is_main_content(bbox, page.rect, block_text):
                    text_blocks.append(block_text.strip())
        
        page_text = " ".join(text_blocks)
        pages_data.append({
            'page_num': page_num + 1,
            'text': page_text,
            'blocks': text_blocks
        })
    
    pdf.close()
    return pages_data

def is_main_content(bbox, page_rect, text):
    """Filter out headers, footers, page numbers, and other non-content"""
    x0, y0, x1, y1 = bbox
    page_width = page_rect.width
    page_height = page_rect.height
    
    # Skip if too close to edges (likely headers/footers)
    margin_threshold = 50
    if (y0 < margin_threshold or 
        y1 > page_height - margin_threshold or
        x0 < margin_threshold or 
        x1 > page_width - margin_threshold):
        
        # But allow if it's substantial content
        if len(text.split()) < 5:
            return False
    
    # Skip page numbers
    if re.match(r'^\s*\d+\s*$', text.strip()):
        return False
    
    # Skip very short text blocks that might be captions/labels
    if len(text.split()) < 3:
        return False
    
    # Skip common textbook elements
    skip_patterns = [
        r'^chapter\s+\d+',
        r'^section\s+\d+',
        r'^figure\s+\d+',
        r'^table\s+\d+',
        r'^index$',
        r'^bibliography$',
        r'^references$',
        r'^contents$',
        r'^appendix',
        r'^\d+\.\d+\s*$',  # Section numbers
        r'^page\s+\d+',
    ]
    
    text_lower = text.lower().strip()
    for pattern in skip_patterns:
        if re.match(pattern, text_lower):
            return False
    
    return True

def clean_and_filter_content(pages_data):
    """Clean extracted text and identify main content sections"""
    all_text = ""
    content_sections = []
    
    for page_data in pages_data:
        page_text = page_data['text']
        
        # Skip pages that look like TOC, index, or references
        if is_content_page(page_text):
            cleaned_text = clean_text(page_text)
            if cleaned_text:
                all_text += cleaned_text + "\n"
                content_sections.append({
                    'page': page_data['page_num'],
                    'text': cleaned_text
                })
    
    return all_text, content_sections

def is_content_page(text):
    """Determine if a page contains main content vs TOC/index/references"""
    text_lower = text.lower()
    word_count = len(text.split())
    
    # Skip if too short
    if word_count < 50:
        return False
    
    # Skip table of contents
    toc_indicators = ['contents', 'chapter', 'section', '...', '….']
    if any(indicator in text_lower for indicator in toc_indicators) and word_count < 200:
        return False
    
    # Skip index pages
    if 'index' in text_lower and word_count < 300:
        return False
    
    # Skip reference/bibliography pages
    ref_indicators = ['references', 'bibliography', 'works cited', 'sources']
    if any(indicator in text_lower for indicator in ref_indicators):
        return False
    
    # Check for high ratio of numbers (might be index or TOC)
    numbers = re.findall(r'\d+', text)
    if len(numbers) / word_count > 0.1:
        return False
    
    return True

def clean_text(text):
    """Clean extracted text"""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove page numbers and section numbers at start of lines
    text = re.sub(r'^\d+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\d+\s*', '', text, flags=re.MULTILINE)
    
    # Remove figure/table references
    text = re.sub(r'\(see figure \d+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(see table \d+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'figure \d+:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'table \d+:', '', text, flags=re.IGNORECASE)
    
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    
    # Remove email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', text)
    
    return text.strip()

def extract_quality_sentences(text, min_length=10, max_length=200):
    """Extract high-quality sentences suitable for quiz generation"""
    doc = nlp(text)
    quality_sentences = []
    
    for sent in doc.sents:
        sent_text = sent.text.strip()
        word_count = len(sent_text.split())
        
        # Filter by length
        if word_count < min_length or word_count > max_length:
            continue
        
        # Skip sentences with too many numbers (likely formulas/references)
        numbers = re.findall(r'\d+', sent_text)
        if len(numbers) > 3:
            continue
        
        # Skip sentences that are mostly punctuation or special characters
        if len(re.sub(r'[^a-zA-Z\s]', '', sent_text)) < len(sent_text) * 0.7:
            continue
        
        # Look for sentences with important concepts (nouns, named entities)
        if has_quiz_worthy_content(sent):
            quality_sentences.append(sent_text)
    
    return quality_sentences

def has_quiz_worthy_content(sent):
    """Check if sentence has content suitable for quiz questions"""
    # Look for key concepts
    important_pos = ['NOUN', 'PROPN', 'ADJ']
    named_entities = [ent.label_ for ent in sent.ents]
    
    # Count important words
    important_words = [token for token in sent if token.pos_ in important_pos and not token.is_stop]
    
    # Must have at least 2 important words
    if len(important_words) < 2:
        return False
    
    # Prefer sentences with named entities
    important_entities = ['PERSON', 'ORG', 'GPE', 'DATE', 'EVENT', 'LAW', 'LANGUAGE']
    if any(label in named_entities for label in important_entities):
        return True
    
    # Or sentences with multiple key concepts
    if len(important_words) >= 3:
        return True
    
    return False

def generate_mcqs_from_textbook(file_storage, num_questions=5):
    """Main function to generate MCQs from textbook PDFs"""
    # Extract text with advanced processing
    pages_data = extract_text_from_pdf_advanced(file_storage)
    
    # Clean and filter content
    all_text, content_sections = clean_and_filter_content(pages_data)
    
    if not all_text.strip():
        return {"error": "No suitable content found for quiz generation"}
    
    # Extract quality sentences
    sentences = extract_quality_sentences(all_text)
    
    if len(sentences) < num_questions:
        return {"warning": f"Only found {len(sentences)} suitable sentences for quiz generation"}
    
    # Generate questions using improved method
    questions = generate_advanced_mcqs(sentences, num_questions)
    
    return {
        "questions": questions,
        "content_pages": len([p for p in pages_data if is_content_page(p['text'])]),
        "total_pages": len(pages_data),
        "sentences_found": len(sentences)
    }

def generate_advanced_mcqs(sentences, num_questions):
    """Generate MCQs with better keyword selection and distractors"""
    # Use TF-IDF to find important terms across all sentences
    vectorizer = TfidfVectorizer(
        stop_words='english', 
        max_features=200,
        ngram_range=(1, 2),  # Include bigrams
        min_df=2  # Must appear in at least 2 sentences
    )
    
    try:
        X = vectorizer.fit_transform(sentences)
        feature_names = vectorizer.get_feature_names_out()
        
        # Get TF-IDF scores for each term
        tfidf_scores = X.toarray()
        
        questions = []
        used_sentences = set()
        
        for i in range(min(num_questions, len(sentences))):
            # Find sentence with high TF-IDF terms that hasn't been used
            best_sentence_idx = find_best_sentence(sentences, tfidf_scores, feature_names, used_sentences)
            
            if best_sentence_idx is None:
                break
                
            sent = sentences[best_sentence_idx]
            used_sentences.add(best_sentence_idx)
            
            # Find best keyword to blank out
            sent_tfidf = tfidf_scores[best_sentence_idx]
            keyword = select_best_keyword(sent, feature_names, sent_tfidf)
            
            if not keyword:
                continue
            
            # Create question by blanking out keyword
            question_text = re.sub(r'\b' + re.escape(keyword) + r'\b', "_____", sent, flags=re.IGNORECASE)
            
            # Generate distractors
            distractors = generate_smart_distractors(keyword, feature_names, sent)
            
            if len(distractors) >= 3:
                options = distractors[:3] + [keyword]
                random.shuffle(options)
                
                questions.append({
                    "question": question_text,
                    "options": options,
                    "answer": keyword,
                    "source_sentence": sent
                })
        
        return questions
    
    except Exception as e:
        # Fallback to simpler method if TF-IDF fails
        return generate_simple_mcqs(sentences, num_questions)

def find_best_sentence(sentences, tfidf_scores, feature_names, used_sentences):
    """Find sentence with highest scoring keywords"""
    best_score = 0
    best_idx = None
    
    for idx, sent in enumerate(sentences):
        if idx in used_sentences:
            continue
            
        # Calculate sentence score based on TF-IDF
        sent_score = sum(tfidf_scores[idx])
        
        if sent_score > best_score:
            best_score = sent_score
            best_idx = idx
    
    return best_idx

def select_best_keyword(sentence, feature_names, tfidf_scores):
    """Select the best keyword to blank out from a sentence"""
    doc = nlp(sentence)
    candidates = []
    
    for i, feature in enumerate(feature_names):
        if feature in sentence.lower() and tfidf_scores[i] > 0:
            # Prefer nouns and proper nouns
            for token in doc:
                if token.lemma_.lower() == feature.lower():
                    if token.pos_ in ['NOUN', 'PROPN']:
                        candidates.append((feature, tfidf_scores[i], 3))
                    elif token.pos_ in ['ADJ', 'VERB']:
                        candidates.append((feature, tfidf_scores[i], 2))
                    else:
                        candidates.append((feature, tfidf_scores[i], 1))
    
    if not candidates:
        return None
    
    # Sort by TF-IDF score and POS preference
    candidates.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return candidates[0][0]

def generate_smart_distractors(correct_answer, all_features, sentence):
    """Generate plausible distractors for the correct answer"""
    doc = nlp(sentence)
    correct_doc = nlp(correct_answer)
    
    # Find words with similar POS tags
    target_pos = None
    for token in correct_doc:
        if not token.is_stop:
            target_pos = token.pos_
            break
    
    distractors = []
    
    # Look for words with same POS in the feature list
    for feature in all_features:
        if feature != correct_answer.lower():
            feature_doc = nlp(feature)
            for token in feature_doc:
                if token.pos_ == target_pos and len(distractors) < 10:
                    distractors.append(feature)
                    break
    
    # If not enough distractors, add random features
    remaining_features = [f for f in all_features if f != correct_answer.lower() and f not in distractors]
    while len(distractors) < 10 and remaining_features:
        distractors.append(remaining_features.pop(0))
    
    return random.sample(distractors, min(3, len(distractors)))

def generate_simple_mcqs(sentences, num_questions):
    """Fallback simple MCQ generation"""
    questions = []
    for i in range(min(num_questions, len(sentences))):
        doc = nlp(sentences[i])
        nouns = [token.text for token in doc if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop]
        
        if nouns:
            keyword = random.choice(nouns)
            question = sentences[i].replace(keyword, "_____")
            distractors = random.sample(nouns, min(3, len(nouns)))
            options = distractors + [keyword]
            random.shuffle(options)
            
            questions.append({
                "question": question,
                "options": options,
                "answer": keyword
            })
    
    return questions

# Keep your existing Cohere functions
def generate_questions_from_prompt(prompt, num_questions=5):
    response = co.generate(
        model="command-r-plus",
        prompt=f"Generate {num_questions} MCQs with 4 options each on the topic: {prompt}. Return them in the format:\n1. Question\nA. option\nB. option\nC. option\nD. option\nAnswer: A",
        max_tokens=800,
        temperature=0.7
    )
    return parse_questions(response.generations[0].text)

def parse_questions(text):
    blocks = re.split(r'\n(?=\d+\.)', text)
    questions = []
    for block in blocks:
        match = re.match(r'\d+\.\s*(.*?)\nA\.\s*(.*?)\nB\.\s*(.*?)\nC\.\s*(.*?)\nD\.\s*(.*?)\nAnswer:\s*([A-D])', block, re.DOTALL)
        if match:
            q, *opts, ans = match.groups()
            answer = opts[ord(ans) - ord('A')]
            questions.append({
                "question": q.strip(),
                "options": [o.strip() for o in opts],
                "answer": answer
            })
    return questions

# Usage example:
# result = generate_mcqs_from_textbook(uploaded_file, num_questions=10)
# if "questions" in result:
#     for i, q in enumerate(result["questions"], 1):
#         print(f"{i}. {q['question']}")
#         for j, option in enumerate(q['options']):
#             print(f"   {chr(65+j)}. {option}")
#         print(f"   Answer: {q['answer']}\n")