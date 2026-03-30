# ============================================
# Frontend Dashboard (Nginx)
# ============================================
FROM nginx:alpine

# Copy static files
COPY index.html /usr/share/nginx/html/index.html
COPY chat.html /usr/share/nginx/html/chat.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
