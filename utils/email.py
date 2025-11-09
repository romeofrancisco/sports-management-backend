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
