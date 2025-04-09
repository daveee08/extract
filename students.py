import streamlit as st
import requests
import fitz

st.set_page_config(page_title="Student Submission", page_icon="🧑‍🎓")

st.title("🧑‍🎓 Submit Your Answers")

filename = st.text_input("Enter the related question filename (ask your teacher):")

mode = st.radio("How do you want to submit your answers?", ["Manual Entry"])

student_answers = []

if filename:
    with st.spinner("Fetching questions..."):
        res = requests.get(f"http://localhost:8000/questions/{filename}")
        if res.status_code == 200:
            questions = res.json()
            st.subheader("Questions from the uploaded file:")
            for i, question in enumerate(questions):
                st.markdown(f"**Question {i + 1}:** {question['question_text']}")

        else:
            st.error("❌ Could not fetch questions from the database.")

if mode == "Manual Entry":
    num_q = st.number_input("How many questions are you answering?", min_value=1, step=1)
    for i in range(int(num_q)):
        ans = st.text_area(f"Answer {i + 1}", key=f"student_ans_{i}")
        student_answers.append(ans)

if student_answers and st.button("Submit for Grading"):
    print(f"Student answers: {student_answers}")

    with st.spinner("Sending answers to be graded..."):
        res = requests.post("http://localhost:8000/grade/", json={
            "filename": filename,
            "answers": student_answers
        })

        if res.status_code == 200:
            graded = res.json()
            st.success("✅ Grading complete!")

            total_score = 0
            total_out_of = 0

            total_questions = len(graded)
            for i, g in enumerate(graded):
                st.markdown(f"### Question {i+1}")
                st.markdown(f"**Question:** {g['question']}")
                st.markdown(f"**Your Answer:** {g['student_answer']}")
                st.markdown(f"**Score:** {g['score']} / {g['out_of']}")
                st.markdown(f"**Feedback:** {g['feedback']}")

                total_score += g['score']
                total_out_of += g['out_of']

            st.markdown(f"### Total Score: {total_score} / {total_out_of}")
        else:
            st.error(f"❌ Failed to grade answers: {res.text}")
