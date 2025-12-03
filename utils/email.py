from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings

def send_set_password_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_link = f"{settings.FRONTEND_URL}/set-password/{uid}/{token}"

    # Plain text fallback
    text_content = f"""
    Hi {user.first_name},
    Please set your password by visiting this link:
    {reset_link}
    """

    # HTML content (rendered from template)
    html_content = render_to_string("emails/set_password_email.html", {
        "user": user,
        "reset_link": reset_link,
    })

    subject = "Welcome! Set Your Password"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [user.email]

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_registration_pending_email(registration):
    """Send email to player after they submit their registration"""
    # Plain text fallback
    text_content = f"""
    Hi {registration.first_name},
    
    Thank you for registering as a player for {registration.sport.name}.
    
    Your registration has been received and is currently being reviewed by our coaching staff.
    You will receive another email once your registration has been reviewed.
    
    If you have any questions, please contact the athletics department.
    
    - UPHSD Sports Management
    """

    # HTML content (rendered from template)
    html_content = render_to_string("emails/registration_pending_email.html", {
        "registration": registration,
    })

    subject = "Registration Received - Pending Approval"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_registration_approved_email(registration, user):
    """Send email to player when their registration is approved"""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_link = f"{settings.FRONTEND_URL}/set-password/{uid}/{token}"

    # Plain text fallback
    text_content = f"""
    Congratulations {registration.first_name}!
    
    Your player registration has been approved!
    
    You have been assigned to:
    - Team: {registration.team.name}
    - Sport: {registration.sport.name}
    - Jersey Number: #{registration.jersey_number}
    
    Your account has been created. Please set your password by visiting this link:
    {reset_link}
    
    We're excited to have you on the team!
    
    - UPHSD Sports Management
    """

    # HTML content (rendered from template)
    html_content = render_to_string("emails/registration_approved_email.html", {
        "registration": registration,
        "reset_link": reset_link,
    })

    subject = "🎉 Registration Approved - Welcome to the Team!"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_registration_rejected_email(registration):
    """Send email to player when their registration is rejected"""
    # Plain text fallback
    text_content = f"""
    Hello {registration.first_name},
    
    We regret to inform you that your player registration for {registration.sport.name} has not been approved.
    
    Reason: {registration.rejection_reason}
    
    If you believe this was a mistake or have questions about this decision, 
    please contact the athletics department for more information.
    
    You may also submit a new registration application if you wish to try again.
    
    Thank you for your interest in joining our sports program.
    
    - UPHSD Sports Management
    """

    # HTML content (rendered from template)
    html_content = render_to_string("emails/registration_rejected_email.html", {
        "registration": registration,
    })

    subject = "Registration Status Update"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    msg = EmailMultiAlternatives(subject, text_content, from_email, to)
    msg.attach_alternative(html_content, "text/html")
    msg.send()
