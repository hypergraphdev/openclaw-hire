# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest  | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue
2. Email: web8stars@gmail.com
3. Include a description and steps to reproduce

We will respond within 48 hours and work with you to address the issue.

## Security Considerations

### SECRET_KEY

The `SECRET_KEY` environment variable is used for JWT token signing. In production:
- Use a strong random string (32+ characters)
- Never commit it to version control
- Rotate periodically

### Database

- MySQL credentials should be set via environment variables
- Default credentials in `.env.example` are for development only

### CORS

- Production deployments should set `SITE_BASE_URL` to restrict CORS origins
- The default `allow_origins=["*"]` is for development convenience only

### Authentication

- Passwords are hashed with PBKDF2-SHA256
- JWT tokens expire after 7 days by default
- Admin privileges are granted to hardcoded email or first registered user
