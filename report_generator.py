# report_generator.py
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit

def generate_report_pdf(content: str, title: str = "Chatbot Report") -> BytesIO:
    """
    Generates a PDF report using ReportLab.
    
    Args:
        content (str): The text content of the report.
        title (str): The title of the report.
        
    Returns:
        BytesIO: A buffer containing the PDF data.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Margins and fonts
    x_margin = 1 * inch
    y_margin = 1 * inch
    y = height - y_margin
    
    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x_margin, y, title)
    y -= 0.5 * inch

    # Body text
    c.setFont("Helvetica", 11)
    max_width = width - 2 * x_margin
    line_height = 14
    
    # Simple word wrapping
    # We split by newlines first to preserve paragraph structure
    paragraphs = content.split("\n")
    
    for paragraph in paragraphs:
        # If paragraph is empty (blank line), just move down
        if not paragraph.strip():
            y -= line_height
            if y < y_margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - y_margin
            continue
            
        # Wrap text
        lines = simpleSplit(paragraph, "Helvetica", 11, max_width)
        
        for line in lines:
            c.drawString(x_margin, y, line)
            y -= line_height
            
            # Page break check
            if y < y_margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - y_margin
        
        # Extra space after paragraph
        y -= 5 
        if y < y_margin:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - y_margin

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def generate_equity_research_html(client, model: str, company_name: str, user_message: str, context_text: str = "") -> str:
    """
    Generates a full HTML equity research report using the LLM with RAG context.
    
    Args:
        client: The initialized LLM client (OpenAI/AzureOpenAI).
        model (str): The model deployment name.
        user_message (str): The user's request containing the company name.
        context_text (str): Retrieved context from search/vector store.
        
    Returns:
        str: The generated HTML content.
    """
    current_time = datetime.now().strftime("%B %Y")
    
    # The HTML template to be used in the prompt
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SageAlpha Capital | Equity Research | {{ company }}</title>
    <style>
        /* Reset & Base */
        body {
            margin: 0;
            padding: 0;
            background-color: #ffffff;
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #222222;
            line-height: 1.5;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }

        /* A4 Container - Max 850px for safe printing */
        .container {
            width: 100%;
            max-width: 850px;
            margin: 0 auto;
            padding: 40px;
            background-color: #ffffff;
            box-sizing: border-box;
            border-top: 8px solid #083154; /* Primary Color */
        }

        /* Header */
        .header {
            width: 100%;
            border-bottom: 1px solid #eeeeee;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }
        
        /* Clearfix for floated header elements */
        .header::after {
            content: "";
            display: table;
            clear: both;
        }

        .logo-area {
            float: left;
            width: 60%;
        }

        .logo-area h1 {
            margin: 0;
            font-size: 26px;
            font-family: Georgia, 'Times New Roman', Times, serif;
            color: #083154;
            letter-spacing: -0.5px;
        }

        .logo-area span {
            color: #2e8b57; /* Accent Color */
            font-weight: 700;
        }

        .logo-sub {
            display: block;
            font-size: 11px;
            letter-spacing: 1.5px;
            color: #666666;
            text-transform: uppercase;
            margin-top: 4px;
        }

        .tagline {
            float: right;
            width: 35%;
            text-align: right;
            font-size: 11px;
            color: #6b6b6b;
            line-height: 1.2;
            padding-top: 5px;
        }

        /* Meta Bar */
        .meta-bar {
            background-color: #083154;
            color: #ffffff;
            padding: 10px 20px;
            font-size: 13px;
            margin-bottom: 30px;
            overflow: hidden; /* Clear floats if any */
        }
        
        .meta-left {
            float: left;
            font-weight: 600;
        }
        
        .meta-right {
            float: right;
            font-weight: 600;
        }

        /* Main Content Layout - Float Based for PDF Compatibility */
        .main-content {
            width: 100%;
            overflow: hidden; /* Clearfix */
        }

        .content-col {
            float: left;
            width: 64%; /* ~2/3 width */
            padding-right: 3%;
            box-sizing: border-box;
        }

        .sidebar-col {
            float: right;
            width: 33%; /* ~1/3 width */
            padding-left: 15px;
            border-left: 1px solid #f0f0f0;
            box-sizing: border-box;
        }

        /* Typography & Elements */
        h2 {
            color: #083154;
            border-bottom: 1px solid #eeeeee;
            padding-bottom: 6px;
            margin: 20px 0 12px 0;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 700;
            clear: both;
        }

        h3 {
            margin: 0 0 5px 0;
            font-size: 22px;
            font-weight: 700;
            color: #081b2b;
        }

        .ticker {
            font-weight: 400;
            color: #666666;
        }

        p {
            font-size: 13px;
            margin-bottom: 12px;
            text-align: justify;
            color: #222222;
        }

        ul {
            padding-left: 18px;
            margin-bottom: 15px;
        }

        li {
            font-size: 13px;
            margin-bottom: 8px;
            color: #222222;
            text-align: justify;
        }

        /* Sidebar Components */
        .rating-box {
            background-color: #f6fff6;
            border: 2px solid #008a00;
            padding: 15px;
            border-radius: 4px;
            text-align: center;
            margin-bottom: 25px;
        }

        .rating-text {
            display: block;
            color: #008a00;
            font-weight: 800;
            font-size: 18px;
            margin-bottom: 5px;
        }

        .target-price {
            display: block;
            font-size: 28px;
            font-weight: 800;
            color: #111111;
        }

        .target-label {
            display: block;
            font-size: 10px;
            color: #666666;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 2px;
        }

        /* Data Table */
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 25px;
        }

        .data-table td {
            padding: 6px 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .data-table .label {
            color: #666666;
            font-weight: 600;
            text-align: left;
        }

        .data-table .val {
            text-align: right;
            color: #000000;
            font-weight: 400;
        }

        /* Financial Table */
        .fin-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-top: 10px;
            font-family: 'Courier New', Courier, monospace;
        }

        .fin-table th {
            text-align: right;
            padding: 6px 4px;
            border-bottom: 2px solid #083154;
            color: #083154;
            font-weight: 700;
        }

        .fin-table td {
            text-align: right;
            padding: 6px 4px;
            border-bottom: 1px solid #f2f2f2;
        }

        .fin-table td:first-child {
            text-align: left;
            font-weight: 700;
        }

        /* Analyst Info */
        .analyst-info {
            margin-top: 30px;
            border-top: 1px solid #eeeeee;
            padding-top: 15px;
        }

        .analyst-label {
            font-weight: 700;
            font-size: 12px;
            margin-bottom: 2px;
            display: block;
        }

        .analyst-name {
            font-size: 12px;
            margin: 0;
        }

        .analyst-email {
            font-size: 11px;
            color: #666666;
            margin: 0;
        }

        /* Footer */
        .footer {
            margin-top: 40px;
            padding-top: 15px;
            border-top: 1px solid #eeeeee;
            text-align: center;
            font-size: 10px;
            color: #888888;
            clear: both;
        }

        /* Print Specifics */
        @media print {
            body { 
                -webkit-print-color-adjust: exact; 
                print-color-adjust: exact; 
            }
            .container {
                width: 100%;
                max-width: 100%;
                padding: 0;
                margin: 0;
                border: none;
            }
            .rating-box {
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body>

<div class="container">
    <!-- Header -->
    <div class="header">
        <div class="logo-area">
            <h1>Sage<span>Alpha</span> Capital</h1>
            <span class="logo-sub">Institutional Equity Research</span>
        </div>
        <div class="tagline">
            Research powered by SageAlpha.ai<br>
            {{ date }}
        </div>
    </div>

    <!-- Meta Bar -->
    <div class="meta-bar">
        <div class="meta-left">Sector: {{ sector }}</div>
        <div class="meta-right">Update Note</div>
    </div>

    <!-- Main Content -->
    <div class="main-content">
        
        <!-- Left Column -->
        <div class="content-col">
            <h3>{{ company }} <span class="ticker">({{ ticker }})</span></h3>
            <p style="font-style: italic; color: #555555; margin-top: 0; margin-bottom: 20px;">
                {{ headline_thesis }}
            </p>

            <h2>Investment Thesis</h2>
            <ul>
                {{ thesis_points }}
            </ul>

            <h2>Key Highlights</h2>
            <ul>
               {{ highlight_points }}
            </ul>

            <h2>Valuation & Methodology</h2>
            {{ valuation_text }}

            <h2>Catalysts (Next 12 Months)</h2>
            <ul>
                {{ catalyst_points }}
            </ul>
            
            <h2>Risks</h2>
            <ul>
                {{ risk_points }}
            </ul>
        </div>

        <!-- Right Column (Sidebar) -->
        <div class="sidebar-col">
            <div class="rating-box">
                <span class="rating-text">{{ rating }}</span>
                <span class="target-price">{{ target_price }}</span>
                <span class="target-label">Price Target (12m)</span>
            </div>

            <table class="data-table">
                <tr>
                    <td class="label">Current Price</td>
                    <td class="val">{{ current_price }}</td>
                </tr>
                <tr>
                    <td class="label">Upside</td>
                    <td class="val" style="color: #008a00; font-weight: 700;">{{ upside }}</td>
                </tr>
                <tr>
                    <td class="label">Market Cap</td>
                    <td class="val">{{ market_cap }}</td>
                </tr>
                <tr>
                    <td class="label">Ent. Value</td>
                    <td class="val">{{ ev }}</td>
                </tr>
                 <tr>
                    <td class="label">Valuation</td>
                    <td class="val">{{ multiple_label }}: {{ multiple_val }}</td>
                </tr>
            </table>

            <h2>Financial Summary</h2>
            <p style="font-size: 11px; color: #666666; margin-bottom: 5px;">(Estimates)</p>
            <table class="fin-table">
                <tr>
                    <th>Year</th>
                    <th>2024E</th>
                    <th>2025E</th>
                    <th>2026E</th>
                </tr>
                <tr>
                    <td>Rev</td>
                    <td>{{ rev_24 }}</td>
                    <td>{{ rev_25 }}</td>
                    <td>{{ rev_26 }}</td>
                </tr>
                <tr>
                    <td>EBITDA</td>
                    <td>{{ ebitda_24 }}</td>
                    <td>{{ ebitda_25 }}</td>
                    <td>{{ ebitda_26 }}</td>
                </tr>
                <tr>
                    <td>EPS</td>
                    <td>{{ eps_24 }}</td>
                    <td>{{ eps_25 }}</td>
                    <td>{{ eps_26 }}</td>
                </tr>
            </table>

            <div class="analyst-info">
                <span class="analyst-label">Analyst</span>
                <p class="analyst-name">SageAlpha Research Team</p>
                <p class="analyst-email">research@sagealpha.ai</p>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <div class="footer">
        © 2025 SageAlpha Capital. All rights reserved. This report is for informational purposes only and does not constitute financial advice. Powered by SageAlpha.ai.
    </div>
</div>

</body>
</html>"""

    system_prompt = f"""You are a Senior Equity Research Analyst at SageAlpha Capital.
    Your task is to generate a professional, high-quality equity research report in HTML format for: "{company_name}".
    
    The user's original request was: "{user_message}"
    
    ### CONTEXT DATA (Use this if relevant, otherwise use your internal knowledge):
    {context_text}
    
    ### INSTRUCTIONS:
    1. **ANALYSIS**: Analyze the company based on the provided Context and your own knowledge. Focus on differentiation, valuation, and catalysts.
    2. **HTML FORMAT**: Use EXACTLY the provided HTML template structure. Fill in the specific placeholders or sections with realistic, high-quality content.
    3. **TONE**: Professional, insightful, concise, and institutional-grade. Avoid generic fluff.
    4. **ACCURACY**: Use real data from the context if available. If specific stats (like current price) are not in context, use your best recent estimate but mark clearly if uncertain, or better, use "N/A" if completely unknown, but prefer realistic estimates for the sake of the report format.
    5. **OUTPUT**: Return ONLY the raw HTML code. Do not wrap in markdown code blocks.

    ### TEMPLATE TO FILL:
    {html_template}
    
    ### REQUIRED REPLACEMENTS:
    - Replace `{{ company }}` and `{{ ticker }}`
    - Replace `{{ date }}` with Today's Date
    - Replace `{{ sector }}` with the correct GICS sector
    - Replace `{{ headline_thesis }}` with a punchy 1-sentence thesis summary
    - Replace `{{ thesis_points }}` with 3 `<li>` items detailing the thesis
    - Replace `{{ highlight_points }}` with 3 `<li>` items highlights
    - Replace `{{ valuation_text }}` with 1-2 paragraphs on valuation logic
    - Replace `{{ catalyst_points }}` with 3 `<li>` items
    - Replace `{{ risk_points }}` with 2-3 `<li>` items
    - Sidebar stats: `{{ rating }}` (BUY/HOLD/SELL), `{{ target_price }}`, `{{ current_price }}`, `{{ upside }}`, `{{ market_cap }}`, `{{ ev }}`, `{{ multiple_label }}`, `{{ multiple_val }}` (e.g. P/E or EV/EBITDA)
    - Financials: Fill the 2024E/2025E/2026E placeholders with plausible numbers.

    Go."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate the full detailed HTML research report for {company_name}"}
            ],
            max_tokens=3500, # Increased for full report
            temperature=0.4, # Lower temperature for more factual/conservative output
        )
        
        html_content = response.choices[0].message.content.strip()
        
        # Cleanup if LLM still adds markdown fences
        if html_content.startswith("```html"):
            html_content = html_content[7:]
        elif html_content.startswith("```"):
            html_content = html_content[3:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
            
        return html_content.strip()
        
    except Exception as e:
        print(f"Error generat report HTML: {e}")
        return f"<h1>Error generat report</h1><p>{str(e)}</p>"