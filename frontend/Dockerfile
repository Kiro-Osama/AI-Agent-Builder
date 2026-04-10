# ============================================
# Frontend Dashboard (Nginx)
# ============================================
FROM nginx:alpine

# Copy static files
COPY index.html /usr/share/nginx/html/index.html
COPY chat.html /usr/share/nginx/html/chat.html
COPY admin.html /usr/share/nginx/html/admin.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js
COPY admin.js /usr/share/nginx/html/admin.js

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
