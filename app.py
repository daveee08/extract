import streamlit as st
import requests
import os
import json

st.set_page_config(page_title="PDF Question Extractor", page_icon="📄")
st.title("📄 Kwakerist - Teacher's Question Extractor")

uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

if uploaded_file:
    if st.button("Extract Questions"):
        with st.spinner("Extracting questions from PDF..."):
            response = requests.post(
                "http://localhost:8000/extract/",
                files={"file": (uploaded_file.name, uploaded_file, "application/pdf")}
            )

            if response.status_code == 200:
                result = response.json()
                filename = result["filename"]
                extracted_data = result["data"]

                image_data = result.get("images", [])
                st.session_state.images = image_data
                st.session_state.questions = extracted_data
                st.session_state.filename = filename

                st.success("✅ Extraction completed successfully!")
            else:
                st.error(f"❌ Error during extraction: {response.text}")

if "questions" in st.session_state:
    st.subheader("✏️ Review & Edit Extracted Questions")

    edited_questions = []

    for i, item in enumerate(st.session_state.questions):
        st.markdown(f"### Question {i + 1}")

        q = st.text_area(
            f"Question {i + 1}",
            value=item.get("question") or "",
            key=f"q_{i}"
        )

        r = st.text_area(
            f"Rubric {i + 1}",
            value=item.get("rubric") or "",
            key=f"r_{i}"
        )

        edited_questions.append({
            "filename": st.session_state.filename,
            "question": q,
            "rubric": r or ""
        })

        if "images" in st.session_state and st.session_state.images:
            st.subheader("🖼️ Extracted Images from PDF")
            for img in st.session_state.images:
                st.markdown(f"**Page {img['page']}**")
                try:
                    with open(img["filename"], "rb") as image_file:
                        st.image(image_file.read(), caption=os.path.basename(img["filename"]))
                except Exception as e:
                    st.warning(f"Unable to load image {img['filename']}: {e}")

    if st.button("✅ Save to Database"):
        with st.spinner("Saving to database..."):
            save_response = requests.post(
                "http://localhost:8000/save/",
                json={"questions": edited_questions, "images": st.session_state.images}
            )

            if save_response.status_code == 200:
                st.success("✅ All questions and images saved to the database!")
                st.session_state.clear()
            else:
                st.error(f"❌ Error saving data: {save_response.text}")
