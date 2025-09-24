FROM nginx:alpine-slim
RUN apk add --no-cache curl
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY src/index.html /usr/share/nginx/html/index.html
COPY images/ /usr/share/nginx/html/images/
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
