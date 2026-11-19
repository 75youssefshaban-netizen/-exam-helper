import io
import pypdf
import PIL.Image
import pypdfium2 as pdfium
import streamlit as st
import google.generativeai as genai

st.set_page_config(
    page_title="مُختصِر - مساعد الامتحانات الذكي",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <meta name="theme-color" content="#0f172a">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="مُختصِر">
    <style>
        .main, .stMarkdown, .stTextInput, .stSelectbox, .stRadio {
            direction: rtl;
            text-align: right;
        }
        .stButton > button {
            border-radius: 10px;
            font-weight: bold;
            padding: 0.6rem 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎯 مُختصِر - مولّد الملخصات وبنك الأسئلة")
st.caption("يدعم ملفات PDF حتى 1000 صفحة (نصي أو Scan) وصور المحاضرات لاستخراج الزيتونة، رادار الامتحان، وبنك الأسئلة.")

if "last_result" not in st.session_state:
    st.session_state.last_result = ""
if "last_title" not in st.session_state:
    st.session_state.last_title = ""

secret_key = ""
try:
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    secret_key = ""

with st.sidebar:
    st.header("⚙️ إعدادات التشغيل")
    if secret_key:
        st.success("🔑 تم تفعيل مفتاح النظام تلقائياً.")
        api_key = secret_key
    else:
        api_key = st.text_input(
            "مفتاح Gemini API",
            type="password",
            placeholder="الصق مفتاح API هنا...",
        )

    model_name = st.selectbox(
        "موديل الذكاء الاصطناعي",
        options=["gemini-1.5-flash", "gemini-1.5-pro"],
        index=0,
    )

    st.markdown("---")
    st.markdown("### 📱 تثبيت على الموبايل")
    st.caption(
        "افتح رابط التطبيق في Chrome أو Safari واضغط (إضافة إلى الشاشة الرئيسية / Add to Home screen)."
    )


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """معرفة عدد صفحات ملف PDF."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)


def extract_text_from_pdf_range(pdf_bytes: bytes, start_page: int, end_page: int) -> str:
    """استخراج النص من نطاق صفحات محدد (1-based inclusive)."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    start_idx = max(0, start_page - 1)
    end_idx = min(total, end_page)

    chunks = []
    for idx in range(start_idx, end_idx):
        txt = reader.pages[idx].extract_text() or ""
        if txt.strip():
            chunks.append(f"--- صفحة {idx + 1} ---\n{txt.strip()}")
    return "\n\n".join(chunks)


def pdf_range_to_images(pdf_bytes: bytes, start_page: int, end_page: int, scale: float = 1.2) -> list:
    """تحويل نطاق صفحات PDF ممسوح ضوئياً (Scan) إلى صور."""
    pdf_doc = pdfium.PdfDocument(pdf_bytes)
    total = len(pdf_doc)
    start_idx = max(0, start_page - 1)
    end_idx = min(total, end_page)

    images = []
    for i in range(start_idx, end_idx):
        page = pdf_doc[i]
        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil()
        if pil_img.mode not in ("RGB", "L"):
            pil_img = pil_img.convert("RGB")
        # تصغير أبعاد الصورة قليلاً لتخفيف الضغط على الذاكرة
        pil_img.thumbnail((1280, 1280))
        images.append(pil_img)
    return images


def load_uploaded_images(uploaded_files) -> list:
    """تحميل الصور المرفوعة وتجهيزها."""
    imgs = []
    for f in uploaded_files:
        f.seek(0)
        img = PIL.Image.open(f)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((1280, 1280))
        imgs.append(img)
    return imgs


def split_text_chunks(text: str, max_chars: int = 180000) -> list:
    """تقسيم النصوص الطويلة جداً (مثل كتب 1000 صفحة) إلى أجزاء متماسكة."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    for i in range(0, len(text), max_chars):
        chunks.append(text[i : i + max_chars])
    return chunks


def generate_study_output(prompt: str, text_data: str = "", images_data: list = None) -> str:
    """إرسال المحتوى إلى Gemini (مع دعم النصوص الضخمة والصور)."""
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel(model_name)

    # لو فيه صور، نبعتها مباشرة
    if images_data:
        content_parts = [prompt] + images_data
        response = model.generate_content(content_parts)
        if not response or not getattr(response, "text", None):
            raise ValueError("لم يتم استلام رد نصي من النموذج.")
        return response.text

    # لو النص متوسط أو قصير، نبعته مرة واحدة
    chunks = split_text_chunks(text_data, max_chars=180000)
    if len(chunks) == 1:
        response = model.generate_content([prompt, chunks[0]])
        if not response or not getattr(response, "text", None):
            raise ValueError("لم يتم استلام رد نصي من النموذج.")
        return response.text

    # لو النص ضخم جداً (مئات الصفحات)، نلخص كل جزء ثم ندمجه في نتيجة نهائية منظمة
    partial_outputs = []
    for idx, part in enumerate(chunks, start=1):
        part_prompt = f"{prompt}\n\nهذا هو الجزء رقم {idx} من {len(chunks)} من الكتاب/الملف:"
        res = model.generate_content([part_prompt, part])
        if res and getattr(res, "text", None):
            partial_outputs.append(f"### الجزء {idx}\n{res.text}")

    combined_text = "\n\n".join(partial_outputs)
    final_prompt = (
        f"أعد صياغة وتنظيم النتائج التالية في إجابة واحدة متكاملة ومنظمة بدون تكرار:\n\n{prompt}"
    )
    final_res = model.generate_content([final_prompt, combined_text[:200000]])
    return final_res.text if (final_res and getattr(final_res, "text", None)) else combined_text


if not api_key or not api_key.strip():
    st.warning("⚠️ لم يتم العثور على مفتاح API. أضفه في Secrets أو أدخله في القائمة الجانبية.")
    st.stop()

st.subheader("📂 1. ارفع محتوى المحاضرة")
mode = st.radio("نوع المحتوى:", ["ملف PDF (حتى 1000 صفحة)", "صور محاضرات"], horizontal=True)

extracted_text = ""
images_list = []
ready = False

if mode == "ملف PDF (حتى 1000 صفحة)":
    pdf_file = st.file_uploader("اختر ملف PDF", type=["pdf"])
    if pdf_file is not None:
        try:
            pdf_bytes = pdf_file.getvalue()
            total_pages = get_pdf_page_count(pdf_bytes)

            if total_pages > 1000:
                st.warning(f"⚠️ الملف يحتوي على {total_pages} صفحة؛ سيتم التعامل مع أول 1000 صفحة فقط.")
                max_allowed_page = 1000
            else:
                st.info(f"📘 عدد صفحات الملف: {total_pages} صفحة.")
                max_allowed_page = total_pages

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                start_page = st.number_input("من صفحة", min_value=1, max_value=max_allowed_page, value=1, step=1)
            with col_p2:
                default_end = min(max_allowed_page, int(start_page) + 29)
                end_page = st.number_input(
                    "إلى صفحة",
                    min_value=int(start_page),
                    max_value=max_allowed_page,
                    value=default_end,
                    step=1,
                )

            with st.spinner("جاري فحص الصفحات المحددة..."):
                extracted_text = extract_text_from_pdf_range(pdf_bytes, int(start_page), int(end_page))

            if extracted_text.strip():
                st.success(f"✅ تم استخراج النص من الصفحات ({int(start_page)} إلى {int(end_page)}) بنجاح ({len(extracted_text):,} حرف).")
                ready = True
            else:
                # في حالة Scan نحدد بحد أقصى 25 صفحة في الدفعة الواحدة لتجنب نفاد الذاكرة
                scan_end = min(int(end_page), int(start_page) + 24)
                if int(end_page) - int(start_page) + 1 > 25:
                    st.warning(
                        f"⚠️ الملف ممسوح ضوئياً (Scan). لتحويله بأمان دون تعطل السيرفر، تم تحديد نطاق ({int(start_page)} إلى {scan_end}) فقط."
                    )
                else:
                    st.info("📄 الملف ممسوح ضوئياً (Scan)؛ جاري تحويل الصفحات المحددة إلى صور...")

                with st.spinner("جاري تحويل الصفحات إلى صور..."):
                    images_list = pdf_range_to_images(pdf_bytes, int(start_page), scan_end, scale=1.2)

                if images_list:
                    st.success(f"✅ تم تحويل {len(images_list)} صفحة إلى صور جاهزة للقراءة.")
                    with st.expander("معاينة صفحات الـ PDF المحوّلة"):
                        st.image(images_list, width=220)
                    ready = True
                else:
                    st.error("❌ تعذر استخراج نص أو صور من هذا النطاق.")
        except Exception as e:
            st.error(f"❌ خطأ أثناء معالجة ملف PDF: {e}")
else:
    uploaded_imgs = st.file_uploader(
        "اختر صورة أو أكثر",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )
    if uploaded_imgs:
        try:
            with st.spinner("جاري تجهيز الصور..."):
                images_list = load_uploaded_images(uploaded_imgs)
            st.success(f"✅ تم تجهيز {len(images_list)} صورة بنجاح.")
            with st.expander("معاينة الصور المرفوعة"):
                st.image(images_list, width=220)
            ready = True
        except Exception as e:
            st.error(f"❌ خطأ أثناء تحميل الصور: {e}")

st.markdown("---")

st.subheader("⚡ 2. اختر الأداة")

if not ready:
    st.info("ارفع ملف PDF أو صوراً أولاً لتفعيل الأدوات.")
else:
    c1, c2, c3 = st.columns(3)

    summary_prompt = """
    أنت مساعد أكاديمي مباشر. لخص المحتوى المرفق في شكل "الزيتونة" بدون أي حشو أو مقدمات طويلة.
    قسّم الإجابة بوضوح إلى:
    1. أهم التعريفات والمصطلحات.
    2. العناصر الأساسية والقوانين / القواعد المهمة.
    3. خلاصة سريعة للمراجعة النهائية.
    """

    radar_prompt = """
    بصفتك أستاذاً جامعياً يضع امتحانات، حلل المحتوى المرفق واستخرج:
    1. رادار الامتحان: أهم النقاط والمفاهيم المتوقع مجيئها في الامتحان مع سبب أهميتها.
    2. تريكات الامتحان: المقارنات، الفروق الدقيقة، الاستثناءات، أو الأرقام والتواريخ التي قد تسبب لخبطة.
    """

    quiz_prompt = """
    بناءً على المحتوى المرفق فقط، أنشئ بنك أسئلة تدريبي:
    - 5 أسئلة اختيار من متعدد (MCQ) بأربعة اختيارات (أ، ب، ج، د).
    - 5 أسئلة صح أم خطأ (True / False).
    ضع الأسئلة أولاً بدون حل، ثم في النهاية أضف قسماً بعنوان "✅ نموذج الإجابة" مع توضيح مختصر لكل إجابة.
    """

    with c1:
        if st.button("📌 الزيتونة", use_container_width=True):
            try:
                with st.spinner("جاري استخراج الزيتونة..."):
                    st.session_state.last_result = generate_study_output(summary_prompt, extracted_text, images_list)
                    st.session_state.last_title = "📌 ملخص الزيتونة"
            except Exception as e:
                st.error(f"❌ خطأ: {e}")

    with c2:
        if st.button("🔥 رادار الامتحان", use_container_width=True):
            try:
                with st.spinner("جاري تحليل نقاط الامتحان..."):
                    st.session_state.last_result = generate_study_output(radar_prompt, extracted_text, images_list)
                    st.session_state.last_title = "🔥 رادار الامتحان"
            except Exception as e:
                st.error(f"❌ خطأ: {e}")

    with c3:
        if st.button("📝 بنك أسئلة", use_container_width=True):
            try:
                with st.spinner("جاري إعداد بنك الأسئلة..."):
                    st.session_state.last_result = generate_study_output(quiz_prompt, extracted_text, images_list)
                    st.session_state.last_title = "📝 بنك الأسئلة"
            except Exception as e:
                st.error(f"❌ خطأ: {e}")

if st.session_state.last_result:
    st.markdown("---")
    st.markdown(f"### {st.session_state.last_title}")
    st.markdown(st.session_state.last_result)

    st.download_button(
        label="⬇️ تحميل النتيجة كملف نصي (TXT)",
        data=st.session_state.last_result.encode("utf-8"),
        file_name="mokhtaser_result.txt",
        mime="text/plain",
  )
