import os
import sys
from app import get_llm_client, get_llm_model
from report_generator import generate_equity_research_html

def main():
    print("Initializing LLM...")
    llm = get_llm_client()
    if not llm:
        print("Error: LLM client not configured.")
        return

    model = get_llm_model()
    company = "Cupid Ltd"
    print(f"Generating report for {company}...")
    
    try:
        # Mock context for testing
        mock_context = "Cupid Ltd is a leading manufacturer of male and female condoms..."
        html_content = generate_equity_research_html(llm, model, f"Generate a research report for {company}", mock_context)
        
        output_file = "cupid_ltd_report.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        print(f"Successfully generated report: {output_file}")
        
    except Exception as e:
        print(f"Error generating report: {e}")

if __name__ == "__main__":
    main()
