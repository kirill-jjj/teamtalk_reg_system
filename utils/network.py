from flask import request as flask_request # Use a more specific import

def get_user_ip_flask():
    """
    Retrieves the user's IP address from the Flask request context.
    Tries X-Forwarded-For header first, then falls back to remote_addr.
    """
    # Check if X-Forwarded-For header exists and is not empty
    x_forwarded_for = flask_request.headers.getlist("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For can be a comma-separated list of IPs, client is usually the first one
        ip = x_forwarded_for.split(',').strip()
    else:
        # Fallback to remote_addr if X-Forwarded-For is not present
        ip = flask_request.remote_addr
    return ip