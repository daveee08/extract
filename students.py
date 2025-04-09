import streamlit as st
import requests
import fitz  # PyMuPDF for reading student answer PDFs

st.set_page_config(page_title="Student Submission", page_icon="🧑‍🎓")

st.title("🧑‍🎓 Submit Your Answers")

filename = st.text_input("Enter the related question filename (ask your teacher):")

mode = st.radio("How do you want to submit your answers?", ["Manual Entry", "Upload Answer PDF"])

student_answers = []

# Show the questions for the given filename
if filename:
    with st.spinner("Fetching questions..."):
        # Call your backend to get questions from the database based on the filename
        res = requests.get(f"http://localhost:8000/questions/{filename}")
        if res.status_code == 200:
            questions = res.json()
            st.subheader("Questions from the uploaded file:")
            for i, question in enumerate(questions):
                st.markdown(f"**Question {i + 1}:** {question['question_text']}")

                # Display associated images-
        else:
            st.error("❌ Could not fetch questions from the database.")


# Handle manual entry or PDF upload for answers
if mode == "Manual Entry":
    num_q = st.number_input("How many questions are you answering?", min_value=1, step=1)
    for i in range(int(num_q)):
        ans = st.text_area(f"Answer {i + 1}", key=f"student_ans_{i}")
        student_answers.append(ans)

elif mode == "Upload Answer PDF":
    pdf_file = st.file_uploader("Upload your answer PDF", type=["pdf"])
    if pdf_file and st.button("Extract Answers from PDF"):
        with st.spinner("Extracting answers..."):
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            student_answers = [ans.strip() for ans in full_text.split("\n\n") if len(ans.strip()) > 20]
            st.success(f"Extracted {len(student_answers)} answers from PDF.")
            for i, ans in enumerate(student_answers):
                st.text_area(f"Answer {i+1}", value=ans, key=f"uploaded_ans_{i}")

# Submit for grading
if student_answers and st.button("Submit for Grading"):
    # Check the student answers before sending for grading
    print(f"Student answers: {student_answers}")  # This helps in debugging

    # Proceed with sending answers for grading
    with st.spinner("Sending answers to be graded..."):
        # Make the request to grade the answers
        res = requests.post("http://localhost:8000/grade/", json={
            "filename": filename,
            "answers": student_answers
        })

        # Handle the response from the grading API
        if res.status_code == 200:
            graded = res.json()
            st.success("✅ Grading complete!")

            # Display the graded results for each question
            total_questions = len(graded)
            for i, g in enumerate(graded):
                st.markdown(f"### Question {i+1}")
                st.markdown(f"**Question:** {g['question']}")
                st.markdown(f"**Your Answer:** {g['student_answer']}")
                st.markdown(f"**Score:** {g['score']} / {g['out_of']}")
                st.markdown(f"**Feedback:** {g['feedback']}")
        else:
            st.error(f"❌ Failed to grade answers: {res.text}")
