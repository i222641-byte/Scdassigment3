FROM nginx:1.27-alpine

RUN addgroup -S rahbar && adduser -S -G rahbar rahbar

COPY index.html /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/nginx.conf

RUN chown -R rahbar:rahbar /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /etc/nginx/nginx.conf

USER rahbar
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
