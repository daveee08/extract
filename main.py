from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List
import fitz
import os
import mysql.connector
import requests
import json
from dotenv import load_dotenv
from fastapi import Form
from typing import Optional

app = FastAPI()

# Helper function to connect to the MySQL database
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="pdf_data"
    )

# Helper function to extract contents from the PDF file
def extract_pdf_contents(file_path):
    doc = fitz.open(file_path)
    full_text = ""
    image_data = []
    seen_images = set()

    for page_num, page in enumerate(doc):
        full_text += page.get_text()

        images = page.get_images(full=True)
        for img_index, img in enumerate(images):
            xref = img[0]

            # Skip duplicate images by checking if we've seen the xref before
            if xref in seen_images:
                continue
            seen_images.add(xref)

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            # Skip tiny images (e.g., logos or backgrounds)
            if base_image["width"] < 100 or base_image["height"] < 100:
                continue

            image_filename = f"temp/image_page{page_num + 1}_{img_index}.{image_ext}"
            with open(image_filename, "wb") as img_file:
                img_file.write(image_bytes)

            image_data.append({
                "page": page_num + 1,
                "filename": image_filename,
                "ext": image_ext
            })

    return full_text, len(doc), image_data

# Helper function to process rubric dynamically
def parse_rubric(rubric_text):
    """
    Parses rubric text to extract levels and scores dynamically.
    The rubric is expected to have different levels with corresponding points.
    Example rubric: 
    Level Accuracy (3 pts) Clarity (3 pts) Examples (3 pts) Total Points
    """
    import re

    # Regular expression pattern to extract "Level" and "pts" (score)
    pattern = r"(\w+)\s*\((\d+)\s*pts\)"
    
    rubric_info = []
    total_score = 0

    # Find all the level-score pairs
    matches = re.findall(pattern, rubric_text)
    for match in matches:
        level, score = match
        rubric_info.append({"level": level, "score": int(score)})
        total_score += int(score)
    
    return rubric_info, total_score

# Helper function to process content using AI (Quasar model)
def process_with_ai(content):
    headers = {
        "Authorization": f"Bearer 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",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openrouter/quasar-alpha",
        "messages": [{
            "role": "user",
            "content": """The following text comes from an academic PDF. 
            Your task is to extract all the questions and any available rubric or marking scheme.
            Format your reply in JSON like this:

            [{"question": "...", "rubric": "..."}]

            Here is the content:
            """ + content
        }]
    }

    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)
        response.raise_for_status()

        response_json = response.json()
        message_content = response_json["choices"][0]["message"]["content"]

        return message_content
    except Exception as e:
        print("AI call failed:", e)
        return ""  # <-- Return empty string on failure


# Pydantic model for extracting and saving question data
class QuestionItem(BaseModel):
    filename: str
    question: str
    rubric: str

@app.post("/extract/") 
async def extract_questions(file: UploadFile = File(...)):
    try:
        os.makedirs("temp", exist_ok=True)
        file_location = f"temp/{file.filename}"
        with open(file_location, "wb") as f:
            f.write(await file.read())
        
        # Extract content and images from the PDF
        raw_text, num_pages, images = extract_pdf_contents(file_location)
        
        # Process extracted content with AI to get questions and rubrics
        ai_json = process_with_ai(raw_text)

        # Clean up Markdown-style code block if present
        if ai_json.strip().startswith("```json"):
            ai_json = ai_json.strip().removeprefix("```json").removesuffix("```").strip()

        try:
            extracted_data = json.loads(ai_json)
        except json.JSONDecodeError as e:
            print("[JSON Error]", e)
            raise ValueError(f"Invalid JSON returned by AI: {ai_json}")

        # Here we modify how the rubrics are processed to be dynamic
        for item in extracted_data:
            rubric_text = item.get('rubric')
            if rubric_text:
                parsed_rubric, _ = parse_rubric(rubric_text)
                item['parsed_rubric'] = parsed_rubric
            else:
                item['parsed_rubric'] = []
        
        return {
            "filename": file.filename,
            "pages": num_pages,
            "data": extracted_data,
            "images": images  # Add list of image file paths and metadata
        }
    except Exception as e:
        print(f"Error during extraction: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# Endpoint to save the extracted questions into the database
@app.post("/save/") 
async def save_questions(questions: List[QuestionItem], images: List[dict]):
    try:
        db = get_db()
        cursor = db.cursor()

        for item in questions:
            # Get associated images for each question (filtered by filename)
            associated_images = [img['filename'] for img in images if img['filename'].startswith(item.filename)]

            # Convert image file paths to a JSON string (you can store them in a comma-separated format as well)
            images_str = json.dumps(associated_images)

            cursor.execute("""
                INSERT INTO pdf_questions (filename, question_text, rubric, images)
                VALUES (%s, %s, %s, %s)
            """, (item.filename, item.question, item.rubric, images_str))

        db.commit()
        cursor.close()
        db.close()
        return {"message": f"Saved {len(questions)} questions and their associated images."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Pydantic model for grading input (student answers)
class GradingInput(BaseModel):
    filename: str
    answers: List[str]  # List of student answers
    

@app.get("/questions/{filename}")
async def get_questions(filename: str):
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT question_text, rubric, images FROM pdf_questions WHERE filename = %s", (filename,))
        questions = cursor.fetchall()
        cursor.close()
        db.close()

        if not questions:
            raise HTTPException(status_code=404, detail="Questions not found for this filename")

        # Prepare the response to include image paths
        for question in questions:
            # If there are images, convert from string (JSON format) to a list
            question["images"] = json.loads(question["images"])
        
        return questions
    except Exception as e:
        return {"error": str(e)}
    
    
@app.post("/grade/") 
async def grade_answers(input: GradingInput):
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT question_text, rubric FROM pdf_questions WHERE filename = %s", (input.filename,))
        questions = cursor.fetchall()

        if not questions:
            raise HTTPException(status_code=404, detail="Questions not found for this filename")

        results = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0

        for i, question in enumerate(questions):
            if i >= len(input.answers):
                break  

            # Parse the rubric to extract points and levels dynamically
            rubric_info, total_points = parse_rubric(question['rubric'])

            ai_prompt = f"""
                        You are a grading assistant. Grade the following student answer based on the question and rubric.

                        Question: {question['question_text']}
                        Rubric: {question['rubric']}
                        Student Answer: {input.answers[i]}

                        The rubric provides different levels with corresponding points. Ensure that you evaluate the answer based on these levels.

                        Return the result in JSON format:
                        {{
                        "score": int,
                        "out_of": {total_points},
                        "feedback": "Detailed explanation..."
                        }}
                        """
            headers = {
                "Authorization": f"Bearer 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",
                "Content-Type": "application/json"
            }
            body = {
                "model": "openrouter/quasar-alpha",
                "messages": [{"role": "user", "content": ai_prompt}]
            }

            response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)

            try:
                ai_result = json.loads(response.json()["choices"][0]["message"]["content"])

                if "score" in ai_result and "out_of" in ai_result and "feedback" in ai_result:
                    cursor.execute("""
                        INSERT INTO graded_answers (filename, question_text, student_answer, score, out_of, feedback)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        input.filename, question['question_text'], input.answers[i],
                        ai_result["score"], ai_result["out_of"], ai_result["feedback"]
                    ))
                    db.commit()

                    results.append({
                        "question": question['question_text'],
                        "student_answer": input.answers[i],
                        "score": ai_result["score"],
                        "out_of": ai_result["out_of"],
                        "feedback": ai_result["feedback"]
                    })

                else:
                    cursor.execute("""
                        INSERT INTO graded_answers (filename, question_text, student_answer, score, out_of, feedback)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        input.filename, question['question_text'], input.answers[i], 0, total_points,
                        "Unable to grade answer due to unexpected AI response."
                    ))
                    db.commit()

                    results.append({
                        "question": question['question_text'],
                        "student_answer": input.answers[i],
                        "score": 0,
                        "out_of": total_points,
                        "feedback": "Unable to grade answer due to unexpected AI response."
                    })

                # Log and accumulate token usage
                usage = response.json().get("usage", {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                total_tokens += prompt_tokens + completion_tokens
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens

                print(f"Prompt tokens used: {prompt_tokens}, Completion tokens used: {completion_tokens}, Total tokens: {total_tokens}")

            except Exception as e:
                print("Error parsing AI response:", e)

        return {
            "results": results,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens
        }

    except Exception as e:
        print(f"Error during grading: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
