import logging
from livekit.agents import function_tool, RunContext
import requests
from langchain_community.tools import DuckDuckGoSearchRun
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os


@function_tool
async def get_weather(
    context: RunContext,  # type: ignore
    city: str) -> str:
    """
    Get the current weather conditions for any city or location.
    
    Use this tool when the user asks about:
    - Current weather, temperature, or climate conditions
    - How hot or cold it is somewhere
    - If it's raining, sunny, cloudy, or any weather condition
    - What to wear based on weather
    - Weather forecasts or current conditions
    - Phrases like "what's the weather", "how's the weather", "is it hot/cold", "is it raining"
    
    Examples of when to use:
    - "What's the weather like in Harare?"
    - "Is it cold in New York?"
    - "How hot is it in Dubai?"
    - "Should I bring an umbrella in London?"
    - "What's the temperature in Tokyo?"
    """
    try:
        response = requests.get(
            f"https://wttr.in/{city}?format=3")
        if response.status_code == 200:
            logging.info(f"Weather for {city}: {response.text.strip()}")
            return response.text.strip()
        else:
            logging.error(f"Failed to get weather for {city}: {response.status_code}")
            return f"Could not retrieve weather for {city}."
    except Exception as e:
        logging.error(f"Error retrieving weather for {city}: {e}")
        return f"An error occurred while retrieving weather for {city}."


@function_tool
async def search_web(
    context: RunContext,  # type: ignore
    query: str) -> str:
    """
    Search the internet for current information, news, facts, or answers to questions.
    
    Use this tool when the user asks about:
    - Current events, news, or recent happenings
    - Information you don't have in your knowledge base
    - Real-time data, statistics, or facts
    - Looking up, finding, or researching something online
    - Questions about topics that require up-to-date information
    - Verification of facts or checking information
    - Product information, reviews, or comparisons
    
    Examples of when to use:
    - "Search for the latest news about AI"
    - "What's happening in the world today?"
    - "Find information about Tesla stock"
    - "Look up the best restaurants in Paris"
    - "Can you research quantum computing?"
    - "What are people saying about the new iPhone?"
    - "Find me information on climate change"
    """
    try:
        results = DuckDuckGoSearchRun().run(tool_input=query)
        logging.info(f"Search results for '{query}': {results}")
        return results
    except Exception as e:
        logging.error(f"Error searching the web for '{query}': {e}")
        return f"An error occurred while searching the web for '{query}'."


@function_tool
async def send_email(
    context: RunContext,  # type: ignore
    to_email: str,
    subject: str,
    message: str,
    cc_email: str | None = None
) -> str:
    """
    Send an email message to someone through Gmail SMTP.
    
    IMPORTANT: This tool CAN and SHOULD be used when the user explicitly requests to send an email.
    Do not refuse or say you cannot send emails - this tool is fully functional.
    
    Use this tool when the user asks to:
    - Send, email, or message someone via email
    - Write or compose an email
    - Contact someone by email
    - Share information through email
    - Forward information to an email address
    - Notify someone via email
    - Phrases like "email this to", "send an email", "can you email", "message them"
    
    Examples of when to use:
    - "Send an email to john@example.com"
    - "Email my boss about the meeting"
    - "Can you message sarah@company.com with the update?"
    - "Send this information to the team"
    - "Email the report to finance@company.com"
    
    Args:
        to_email: Recipient email address (must be a valid email format)
        subject: Email subject line (what the email is about)
        message: Email body content (the actual message to send)
        cc_email: Optional CC email address
    """
    logging.info(f"Attempting to send email to {to_email} with subject: {subject}")
    
    try:
        # Gmail SMTP configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587

        # Get credentials from environment variables
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")

        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials not found in environment variables")
            return "I cannot send the email because Gmail credentials are not configured in the system. Please ask the administrator to set up GMAIL_USER and GMAIL_APP_PASSWORD in the environment variables."

        logging.info(f"Using Gmail account: {gmail_user}")

        # Create message
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject

        # Add CC if provided
        recipients = [to_email]
        if cc_email:
            msg['Cc'] = cc_email
            recipients.append(cc_email)

        # Attach message body
        msg.attach(MIMEText(message, 'plain'))

        # Connect to Gmail SMTP server
        logging.info("Connecting to Gmail SMTP server...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable TLS encryption
        
        logging.info("Authenticating with Gmail...")
        server.login(gmail_user, gmail_password)

        # Send email
        logging.info("Sending email...")
        text = msg.as_string()
        server.sendmail(gmail_user, recipients, text)
        server.quit()

        logging.info(f"Email sent successfully to {to_email}")
        return f"Email sent successfully to {to_email} with subject '{subject}'"

    except smtplib.SMTPAuthenticationError as e:
        error_msg = f"Gmail authentication failed: {str(e)}. Please ensure you're using a Gmail App Password (not your regular password) and that it's correctly configured."
        logging.error(error_msg)
        return error_msg
    except smtplib.SMTPException as e:
        error_msg = f"SMTP error occurred: {str(e)}"
        logging.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Error sending email: {str(e)}"
        logging.error(error_msg)
        return error_msg




