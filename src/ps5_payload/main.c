#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef PS5_DOWNLOADER_PORT
#define PS5_DOWNLOADER_PORT 2634
#endif

#ifndef MAX_NATIVE_DOWNLOAD_BYTES
#define MAX_NATIVE_DOWNLOAD_BYTES 0
#endif

#define DATA_ROOT "/data/test"
#define LOG_PATH DATA_ROOT "/ps5-downloader.log"
#define PID_PATH DATA_ROOT "/ps5-downloader.pid"
#define CONFIG_PATH DATA_ROOT "/ps5-downloader.conf"
#define NANODNS_LOG_PATH "/data/nanodns/nanodns.log"
#define MAX_BODY 16384
#define MAX_URL 2048
#define MAX_PATH 512
#define MAX_DOWNLOADS 16
#define PROGRESS_LOG_STEP (1024 * 1024)
#define DOWNLOAD_BUFFER_BYTES (256 * 1024)
#define BYTE_UPDATE_STEP (256 * 1024)
#define SOCKET_BUFFER_BYTES (1024 * 1024)
#define SOCKET_TIMEOUT_SEC 20
#define HELPER_TIMEOUT_SEC 45
#define SEGMENTED_MIN_BYTES (8 * 1024 * 1024)
#define SEGMENTED_CONNECTIONS 4
#define SEGMENT_BUFFER_BYTES (128 * 1024)
#define LOG_RESPONSE_BYTES 65536

typedef struct parsed_url {
  char host[256];
  char host_header[256];
  char path[MAX_URL];
  char port[8];
} parsed_url_t;

typedef struct http_meta {
  int status;
  long long content_length;
  int accepts_ranges;
  char filename[192];
  char location[MAX_URL];
} http_meta_t;

typedef struct download_item {
  int id;
  char original_url[MAX_URL];
  char resolved_url[MAX_URL];
  char filename[192];
  char path[MAX_PATH];
  char state[32];
  char error[256];
  long long bytes;
  long long content_length;
  int http_status;
} download_item_t;


static download_item_t g_downloads[MAX_DOWNLOADS];
static int g_download_count = 0;
static int g_next_id = 1;
static volatile int g_shutdown = 0;
static pthread_mutex_t g_downloads_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_t g_worker_thread;
static int g_worker_started = 0;
static char g_download_dir[MAX_PATH] = DATA_ROOT;
static char g_resolver_url[MAX_URL] = "";

static void log_line(const char *fmt, ...);

static long long native_limit(void) {
  return (long long)MAX_NATIVE_DOWNLOAD_BYTES;
}

static int limit_enabled(void) {
  return native_limit() > 0;
}

static long long now_ms(void) {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (long long)tv.tv_sec * 1000LL + (long long)(tv.tv_usec / 1000);
}

static int validate_download_dir(const char *path) {
  if (!path || !path[0]) {
    return 0;
  }
  if (strncmp(path, "/data/", 6) && strcmp(path, "/data")) {
    return 0;
  }
  if (strstr(path, "..") || strchr(path, '\n') || strchr(path, '\r') || strchr(path, '\\')) {
    return 0;
  }
  if (strlen(path) >= MAX_PATH - 220) {
    return 0;
  }
  return 1;
}

static int validate_download_file_path(const char *path) {
  if (!path || !path[0]) {
    return 0;
  }
  if (strncmp(path, "/data/", 6)) {
    return 0;
  }
  if (strstr(path, "..") || strchr(path, '\n') || strchr(path, '\r') || strchr(path, '\\')) {
    return 0;
  }
  if (path[strlen(path) - 1] == '/') {
    return 0;
  }
  return 1;
}

static int unlink_download_path(const char *path, const char *label, int id) {
  if (!validate_download_file_path(path)) {
    log_line("skip unsafe delete id=%d label=%s path=%s", id, label, path ? path : "");
    return -1;
  }
  if (unlink(path) == 0) {
    log_line("deleted file id=%d label=%s path=%s", id, label, path);
    return 1;
  }
  if (errno == ENOENT) {
    log_line("delete file already absent id=%d label=%s path=%s", id, label, path);
    return 0;
  }
  log_line("delete file failed id=%d label=%s path=%s errno=%d", id, label, path, errno);
  return -1;
}

static void ensure_download_dir(void) {
  mkdir("/data", 0755);
  mkdir(g_download_dir, 0755);
}

static void load_config(void) {
  FILE *fp = fopen(CONFIG_PATH, "r");
  if (!fp) {
    return;
  }
  char line[MAX_PATH + 64];
  while (fgets(line, sizeof(line), fp)) {
    if (!strncmp(line, "download_dir=", 13)) {
      char *value = line + 13;
      value[strcspn(value, "\r\n")] = 0;
      if (validate_download_dir(value)) {
        snprintf(g_download_dir, sizeof(g_download_dir), "%s", value);
      }
    } else if (!strncmp(line, "resolver_url=", 13)) {
      char *value = line + 13;
      value[strcspn(value, "\r\n")] = 0;
      if (!strncmp(value, "http://", 7) && strlen(value) < sizeof(g_resolver_url)) {
        snprintf(g_resolver_url, sizeof(g_resolver_url), "%s", value);
      }
    }
  }
  fclose(fp);
}

static void save_config(void) {
  FILE *fp = fopen(CONFIG_PATH, "w");
  if (!fp) {
    return;
  }
  fprintf(fp, "download_dir=%s\n", g_download_dir);
  fprintf(fp, "resolver_url=%s\n", g_resolver_url);
  fclose(fp);
}

static void log_line(const char *fmt, ...) {
  FILE *fp = fopen(LOG_PATH, "a");
  if (!fp) {
    return;
  }
  time_t now = time(NULL);
  fprintf(fp, "%lld ", (long long)now);
  va_list ap;
  va_start(ap, fmt);
  vfprintf(fp, fmt, ap);
  va_end(ap);
  fprintf(fp, "\n");
  fclose(fp);
}

static long long file_size_or_negative(const char *path) {
  struct stat st;
  if (stat(path, &st) < 0) {
    return -1;
  }
  return (long long)st.st_size;
}

static int write_all(int fd, const char *data, size_t len) {
  while (len > 0) {
    ssize_t written = write(fd, data, len);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -1;
    }
    data += written;
    len -= (size_t)written;
  }
  return 0;
}

static int pwrite_all_at(int fd, const char *data, size_t len, long long *offset) {
  while (len > 0) {
    ssize_t written = pwrite(fd, data, len, (off_t)*offset);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -1;
    }
    if (written == 0) {
      return -1;
    }
    *offset += written;
    data += written;
    len -= (size_t)written;
  }
  return 0;
}

static void send_response(int client, const char *status, const char *content_type, const char *body) {
  char header[512];
  size_t body_len = strlen(body);
  int header_len = snprintf(header, sizeof(header),
                            "HTTP/1.1 %s\r\n"
                            "Content-Type: %s\r\n"
                            "Content-Length: %zu\r\n"
                            "Connection: close\r\n"
                            "Access-Control-Allow-Origin: *\r\n"
                            "Access-Control-Allow-Methods: GET,POST,OPTIONS\r\n"
                            "Access-Control-Allow-Headers: content-type\r\n"
                            "\r\n",
                            status, content_type, body_len);
  if (header_len > 0) {
    write_all(client, header, (size_t)header_len);
    write_all(client, body, body_len);
  }
}

static void log_response(const char *method, const char *path, const char *status) {
  log_line("response method=%s path=%s status=%s", method, path, status);
}

static void json_escape(const char *input, char *out, size_t out_len) {
  size_t j = 0;
  for (size_t i = 0; input[i] && j + 1 < out_len; i++) {
    unsigned char c = (unsigned char)input[i];
    if (c == '"' || c == '\\') {
      if (j + 2 >= out_len) {
        break;
      }
      out[j++] = '\\';
      out[j++] = (char)c;
    } else if (c == '\n') {
      if (j + 2 >= out_len) {
        break;
      }
      out[j++] = '\\';
      out[j++] = 'n';
    } else if (c == '\r') {
      if (j + 2 >= out_len) {
        break;
      }
      out[j++] = '\\';
      out[j++] = 'r';
    } else if (c == '\t') {
      if (j + 2 >= out_len) {
        break;
      }
      out[j++] = '\\';
      out[j++] = 't';
    } else if (c < 32) {
      out[j++] = '_';
    } else {
      out[j++] = (char)c;
    }
  }
  out[j] = 0;
}

static int starts_with(const char *s, const char *prefix) {
  return strncmp(s, prefix, strlen(prefix)) == 0;
}

static char *strcasestr_local(const char *haystack, const char *needle) {
  size_t nlen = strlen(needle);
  if (!nlen) {
    return (char *)haystack;
  }
  for (const char *p = haystack; *p; p++) {
    if (!strncasecmp(p, needle, nlen)) {
      return (char *)p;
    }
  }
  return NULL;
}

static void sanitize_filename(const char *input, char *out, size_t out_len) {
  size_t j = 0;
  const char *name = strrchr(input, '/');
  name = name ? name + 1 : input;
  if (!*name) {
    name = "download.bin";
  }
  for (size_t i = 0; name[i] && j + 1 < out_len; i++) {
    char c = name[i];
    if (c == '?' || c == '#') {
      break;
    }
    if ((unsigned char)c < 32 || strchr("<>:\"\\|?*/", c)) {
      out[j++] = '_';
    } else {
      out[j++] = c;
    }
  }
  while (j > 0 && (out[j - 1] == ' ' || out[j - 1] == '.')) {
    j--;
  }
  out[j] = 0;
  if (!out[0] || out[0] == '.') {
    snprintf(out, out_len, "download.bin");
  }
}

static void url_decode_inplace(char *s, int plus_as_space) {
  char *src = s;
  char *dst = s;
  while (*src) {
    if (*src == '%' && isxdigit((unsigned char)src[1]) && isxdigit((unsigned char)src[2])) {
      char hex[3] = {src[1], src[2], 0};
      *dst++ = (char)strtol(hex, NULL, 16);
      src += 3;
    } else if (plus_as_space && *src == '+') {
      *dst++ = ' ';
      src++;
    } else {
      *dst++ = *src++;
    }
  }
  *dst = 0;
}

static int copy_one_url(const char *p, char *url, size_t url_len) {
  size_t i = 0;
  while (p[i] && !isspace((unsigned char)p[i]) && p[i] != '"' && p[i] != '\'' && p[i] != '<' && p[i] != '>' && p[i] != '\\' && i + 1 < url_len) {
    url[i] = p[i];
    i++;
  }
  url[i] = 0;
  char *end = strchr(url, ',');
  if (end) {
    *end = 0;
  }
  return url[0] ? 0 : -1;
}

static int is_noise_url(const char *url) {
  if (strstr(url, "://accounts.google.com/") ||
      strstr(url, "://support.google.com/") ||
      strstr(url, "://policies.google.com/") ||
      strstr(url, ".gstatic.com/") ||
      strstr(url, ".googleusercontent.com/") ||
      strstr(url, "://www.google.com/url") ||
      strstr(url, "://www.google.com/search")) {
    return 1;
  }
  return 0;
}

static void encode_http_path(const char *input, char *out, size_t out_len) {
  size_t j = 0;
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; input[i] && j + 1 < out_len; i++) {
    unsigned char c = (unsigned char)input[i];
    if (c <= 32 || c == '"' || c == '\'' || c == '<' || c == '>' || c == '\\' || c == '[' || c == ']' || c == '^' || c == '`' || c == '{' || c == '|' || c == '}') {
      if (j + 3 >= out_len) {
        break;
      }
      out[j++] = '%';
      out[j++] = hex[c >> 4];
      out[j++] = hex[c & 15];
    } else {
      out[j++] = (char)c;
    }
  }
  out[j] = 0;
}

static void encode_query_value(const char *input, char *out, size_t out_len) {
  size_t j = 0;
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; input[i] && j + 1 < out_len; i++) {
    unsigned char c = (unsigned char)input[i];
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
      out[j++] = (char)c;
    } else {
      if (j + 3 >= out_len) {
        break;
      }
      out[j++] = '%';
      out[j++] = hex[c >> 4];
      out[j++] = hex[c & 15];
    }
  }
  out[j] = 0;
}

static int extract_urls(const char *body, char urls[][MAX_URL], int max_urls) {
  int count = 0;
  const char *scan = body;
  while (*scan && count < max_urls) {
    const char *p = strstr(scan, "http://");
    const char *q = strstr(scan, "https://");
    const char *cur = (!p || (q && q < p)) ? q : p;
    if (!cur) {
      break;
    }
    char candidate[MAX_URL];
    if (copy_one_url(cur, candidate, sizeof(candidate)) == 0 && !is_noise_url(candidate)) {
      int duplicate = 0;
      for (int i = 0; i < count; i++) {
        if (!strcmp(urls[i], candidate)) {
          duplicate = 1;
          break;
        }
      }
      if (!duplicate) {
        snprintf(urls[count], MAX_URL, "%s", candidate);
        count++;
      }
    }
    scan = cur + 8;
  }
  return count;
}

static int extract_first_url(const char *body, char *url, size_t url_len) {
  char urls[1][MAX_URL];
  int count = extract_urls(body, urls, 1);
  if (count <= 0) {
    return -1;
  }
  snprintf(url, url_len, "%s", urls[0]);
  return 0;
}

static void remove_host_override(char *raw_path, char *host_header, size_t host_header_len) {
  char *marker = strstr(raw_path, "__ps5_host=");
  if (!marker) {
    return;
  }
  char *value = marker + strlen("__ps5_host=");
  char override[256];
  size_t i = 0;
  while (value[i] && value[i] != '&' && value[i] != '#' && i + 1 < sizeof(override)) {
    override[i] = value[i];
    i++;
  }
  override[i] = 0;
  url_decode_inplace(override, 0);
  if (override[0]) {
    snprintf(host_header, host_header_len, "%s", override);
  }

  char *start = marker;
  if (start > raw_path && (*(start - 1) == '?' || *(start - 1) == '&')) {
    start--;
  }
  char *end = value + i;
  if (*end == '&') {
    end++;
  }
  memmove(start, end, strlen(end) + 1);
  size_t len = strlen(raw_path);
  while (len > 0 && (raw_path[len - 1] == '?' || raw_path[len - 1] == '&')) {
    raw_path[len - 1] = 0;
    len--;
  }
}

static int parse_http_url(const char *url, parsed_url_t *parsed) {
  if (!starts_with(url, "http://")) {
    return -1;
  }
  const char *p = url + 7;
  const char *slash = strchr(p, '/');
  size_t host_len = slash ? (size_t)(slash - p) : strlen(p);
  if (host_len == 0 || host_len >= sizeof(parsed->host)) {
    return -1;
  }
  char hostport[256];
  memcpy(hostport, p, host_len);
  hostport[host_len] = 0;
  char host_header[256];
  snprintf(host_header, sizeof(host_header), "%s", hostport);
  char *colon = strrchr(hostport, ':');
  if (colon) {
    *colon = 0;
    snprintf(parsed->port, sizeof(parsed->port), "%s", colon + 1);
  } else {
    snprintf(parsed->port, sizeof(parsed->port), "80");
  }
  snprintf(parsed->host, sizeof(parsed->host), "%s", hostport);
  snprintf(parsed->host_header, sizeof(parsed->host_header), "%s", host_header);
  char raw_path[MAX_URL];
  snprintf(raw_path, sizeof(raw_path), "%s", slash ? slash : "/");
  remove_host_override(raw_path, parsed->host_header, sizeof(parsed->host_header));
  encode_http_path(raw_path, parsed->path, sizeof(parsed->path));
  return 0;
}

static int connect_http_with_timeout(const parsed_url_t *parsed, int timeout_sec) {
  struct addrinfo hints;
  struct addrinfo *res = NULL;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_STREAM;
  int gai = getaddrinfo(parsed->host, parsed->port, &hints, &res);
  if (gai != 0 || !res) {
    log_line("getaddrinfo failed host=%s port=%s rc=%d", parsed->host, parsed->port, gai);
    return -1;
  }
  log_line("connect begin host=%s port=%s", parsed->host, parsed->port);
  int fd = -1;
  for (struct addrinfo *ai = res; ai; ai = ai->ai_next) {
    fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
    if (fd < 0) {
      continue;
    }
    if (connect(fd, ai->ai_addr, ai->ai_addrlen) == 0) {
      struct timeval timeout;
      timeout.tv_sec = timeout_sec;
      timeout.tv_usec = 0;
      int sockbuf = SOCKET_BUFFER_BYTES;
      setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
      setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
      setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &sockbuf, sizeof(sockbuf));
      setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &sockbuf, sizeof(sockbuf));
      break;
    }
    close(fd);
    fd = -1;
  }
  freeaddrinfo(res);
  if (fd < 0) {
    log_line("connect failed host=%s port=%s errno=%d", parsed->host, parsed->port, errno);
  } else {
    int actual_rcv = 0;
    int actual_snd = 0;
    socklen_t opt_len = sizeof(actual_rcv);
    getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &actual_rcv, &opt_len);
    opt_len = sizeof(actual_snd);
    getsockopt(fd, SOL_SOCKET, SO_SNDBUF, &actual_snd, &opt_len);
    log_line("connect ok host=%s port=%s rcvbuf=%d sndbuf=%d", parsed->host, parsed->port, actual_rcv, actual_snd);
  }
  return fd;
}

static int connect_http(const parsed_url_t *parsed) {
  return connect_http_with_timeout(parsed, SOCKET_TIMEOUT_SEC);
}

static int read_headers(int fd, char *headers, size_t headers_len, char *body_prefix, size_t body_prefix_cap, size_t *body_prefix_len) {
  size_t used = 0;
  *body_prefix_len = 0;
  while (used + 1 < headers_len) {
    char buf[1024];
    ssize_t got = read(fd, buf, sizeof(buf));
    if (got <= 0) {
      return -1;
    }
    if (used + (size_t)got >= headers_len) {
      got = (ssize_t)(headers_len - used - 1);
    }
    memcpy(headers + used, buf, (size_t)got);
    used += (size_t)got;
    headers[used] = 0;
    char *end = strstr(headers, "\r\n\r\n");
    if (end) {
      size_t header_bytes = (size_t)(end + 4 - headers);
      size_t extra = used - header_bytes;
      if (extra > 0 && body_prefix && body_prefix_len) {
        if (extra > body_prefix_cap) {
          extra = body_prefix_cap;
        }
        memcpy(body_prefix, headers + header_bytes, extra);
        *body_prefix_len = extra;
      }
      headers[header_bytes] = 0;
      return 0;
    }
  }
  return -1;
}

static void parse_headers(const char *headers, http_meta_t *meta) {
  memset(meta, 0, sizeof(*meta));
  meta->content_length = -1;
  sscanf(headers, "HTTP/%*s %d", &meta->status);
  char *cl = strcasestr_local(headers, "\nContent-Length:");
  if (cl) {
    meta->content_length = atoll(cl + strlen("\nContent-Length:"));
  }
  char *ar = strcasestr_local(headers, "\nAccept-Ranges:");
  if (ar && strcasestr_local(ar, "bytes")) {
    meta->accepts_ranges = 1;
  }
  char *cd = strcasestr_local(headers, "\nContent-Disposition:");
  if (cd) {
    char *fn = strcasestr_local(cd, "filename=");
    if (fn) {
      fn += strlen("filename=");
      while (*fn == '"' || *fn == '\'' || *fn == ' ') {
        fn++;
      }
      char raw[192];
      size_t i = 0;
      while (fn[i] && fn[i] != '"' && fn[i] != '\'' && fn[i] != ';' && fn[i] != '\r' && fn[i] != '\n' && i + 1 < sizeof(raw)) {
        raw[i] = fn[i];
        i++;
      }
      raw[i] = 0;
      sanitize_filename(raw, meta->filename, sizeof(meta->filename));
    }
  }
  char *loc = strcasestr_local(headers, "\nLocation:");
  if (loc) {
    loc += strlen("\nLocation:");
    while (*loc == ' ' || *loc == '\t') {
      loc++;
    }
    size_t i = 0;
    while (loc[i] && loc[i] != '\r' && loc[i] != '\n' && i + 1 < sizeof(meta->location)) {
      meta->location[i] = loc[i];
      i++;
    }
    meta->location[i] = 0;
  }
}

static int http_get_text(const char *url, char *out, size_t out_len) {
  if (!out || out_len == 0) {
    return -1;
  }
  out[0] = 0;
  parsed_url_t parsed;
  if (parse_http_url(url, &parsed) < 0) {
    return -1;
  }
  int fd = connect_http_with_timeout(&parsed, HELPER_TIMEOUT_SEC);
  if (fd < 0) {
    return -1;
  }
  char req[MAX_URL + 512];
  int len = snprintf(req, sizeof(req),
                     "GET %s HTTP/1.1\r\n"
                     "Host: %s\r\n"
                     "User-Agent: ps5-downloader/0.3-native\r\n"
                     "Connection: close\r\n\r\n",
                     parsed.path, parsed.host_header);
  if (len <= 0 || write_all(fd, req, (size_t)len) < 0) {
    close(fd);
    return -1;
  }
  char headers[4096];
  char prefix[1024];
  size_t prefix_len = 0;
  if (read_headers(fd, headers, sizeof(headers), prefix, sizeof(prefix), &prefix_len) < 0) {
    close(fd);
    return -1;
  }
  http_meta_t meta;
  parse_headers(headers, &meta);
  if (meta.status < 200 || meta.status >= 300) {
    close(fd);
    log_line("http_get_text status=%d url=%s", meta.status, url);
    return -1;
  }
  size_t used = 0;
  if (prefix_len > 0) {
    if (prefix_len >= out_len) {
      prefix_len = out_len - 1;
    }
    memcpy(out, prefix, prefix_len);
    used = prefix_len;
  }
  while (used + 1 < out_len) {
    ssize_t got = read(fd, out + used, out_len - 1 - used);
    if (got < 0) {
      if (errno == EINTR) {
        continue;
      }
      close(fd);
      return -1;
    }
    if (got == 0) {
      break;
    }
    used += (size_t)got;
  }
  close(fd);
  out[used] = 0;
  return used > 0 ? 0 : -1;
}

static int http_probe(const char *url, http_meta_t *meta) {
  parsed_url_t parsed;
  if (parse_http_url(url, &parsed) < 0) {
    return -1;
  }
  int fd = connect_http(&parsed);
  if (fd < 0) {
    return -1;
  }
  log_line("probe begin url=%s", url);
  char req[MAX_URL + 512];
  int len = snprintf(req, sizeof(req),
                     "HEAD %s HTTP/1.1\r\n"
                     "Host: %s\r\n"
                     "User-Agent: ps5-downloader/0.3-native\r\n"
                     "Connection: close\r\n\r\n",
                     parsed.path, parsed.host_header);
  if (len <= 0 || write_all(fd, req, (size_t)len) < 0) {
    close(fd);
    return -1;
  }
  char headers[8192];
  char dummy[1];
  size_t dummy_len = 0;
  int rc = read_headers(fd, headers, sizeof(headers), dummy, sizeof(dummy), &dummy_len);
  close(fd);
  if (rc < 0) {
    return -1;
  }
  parse_headers(headers, meta);
  log_line("probe url=%s status=%d content_length=%lld ranges=%d filename=%s location=%.240s", url, meta->status, meta->content_length, meta->accepts_ranges, meta->filename, meta->location);
  return 0;
}

static long long local_file_size(const char *path) {
  struct stat st;
  if (stat(path, &st) < 0) {
    return -1;
  }
  return (long long)st.st_size;
}

static void update_item_bytes(download_item_t *item, long long bytes) {
  if (!item) {
    return;
  }
  pthread_mutex_lock(&g_downloads_lock);
  item->bytes = bytes;
  pthread_mutex_unlock(&g_downloads_lock);
}

static int item_stop_requested(download_item_t *item) {
  int result = 0;
  pthread_mutex_lock(&g_downloads_lock);
  if (item && !strcmp(item->state, "cancelled")) {
    result = 1;
  } else if (item && !strcmp(item->state, "paused")) {
    result = 2;
  }
  pthread_mutex_unlock(&g_downloads_lock);
  return result;
}

typedef struct segmented_shared {
  download_item_t *item;
  const char *url;
  const char *part_path;
  long long expected_total;
  long long total_written;
  long long next_update;
  int failed;
  int stop_code;
  pthread_mutex_t lock;
} segmented_shared_t;

typedef struct segment_task {
  segmented_shared_t *shared;
  int index;
  long long start;
  long long end;
  int rc;
} segment_task_t;

static int segmented_should_stop(segmented_shared_t *shared) {
  int stop = item_stop_requested(shared->item);
  pthread_mutex_lock(&shared->lock);
  if (stop && !shared->stop_code) {
    shared->stop_code = stop;
  }
  int result = shared->failed || shared->stop_code;
  pthread_mutex_unlock(&shared->lock);
  return result;
}

static void segmented_mark_failed(segmented_shared_t *shared, int rc) {
  pthread_mutex_lock(&shared->lock);
  if (!shared->failed) {
    shared->failed = rc ? rc : -1;
  }
  pthread_mutex_unlock(&shared->lock);
}

static void segmented_add_bytes(segmented_shared_t *shared, long long bytes) {
  int should_update = 0;
  long long total = 0;
  pthread_mutex_lock(&shared->lock);
  shared->total_written += bytes;
  if (shared->total_written >= shared->next_update || shared->total_written >= shared->expected_total) {
    should_update = 1;
    while (shared->next_update <= shared->total_written) {
      shared->next_update += BYTE_UPDATE_STEP;
    }
  }
  total = shared->total_written;
  pthread_mutex_unlock(&shared->lock);
  if (should_update) {
    update_item_bytes(shared->item, total);
  }
}

static void *segment_worker_main(void *arg_ptr) {
  segment_task_t *task = (segment_task_t *)arg_ptr;
  segmented_shared_t *shared = task->shared;
  task->rc = -1;
  parsed_url_t parsed;
  if (parse_http_url(shared->url, &parsed) < 0) {
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  int fd = connect_http(&parsed);
  if (fd < 0) {
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  char req[MAX_URL + 512];
  int len = snprintf(req, sizeof(req),
                     "GET %s HTTP/1.1\r\n"
                     "Host: %s\r\n"
                     "User-Agent: ps5-downloader/0.3-native\r\n"
                     "Range: bytes=%lld-%lld\r\n"
                     "Connection: close\r\n\r\n",
                     parsed.path, parsed.host_header, task->start, task->end);
  if (len <= 0 || write_all(fd, req, (size_t)len) < 0) {
    close(fd);
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  char headers[8192];
  char prefix[4096];
  size_t prefix_len = 0;
  if (read_headers(fd, headers, sizeof(headers), prefix, sizeof(prefix), &prefix_len) < 0) {
    close(fd);
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  http_meta_t meta;
  parse_headers(headers, &meta);
  if (meta.status != 206) {
    log_line("segment %d refused range status=%d start=%lld end=%lld", task->index, meta.status, task->start, task->end);
    close(fd);
    segmented_mark_failed(shared, -4);
    task->rc = -4;
    return NULL;
  }
  int out = open(shared->part_path, O_WRONLY, 0644);
  if (out < 0) {
    log_line("segment %d open failed path=%s errno=%d", task->index, shared->part_path, errno);
    close(fd);
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  char *buf = malloc(SEGMENT_BUFFER_BYTES);
  if (!buf) {
    close(out);
    close(fd);
    segmented_mark_failed(shared, -1);
    return NULL;
  }
  long long offset = task->start;
  long long remaining = task->end - task->start + 1;
  if (prefix_len > 0) {
    size_t write_len = prefix_len;
    if ((long long)write_len > remaining) {
      write_len = (size_t)remaining;
    }
    if (pwrite_all_at(out, prefix, write_len, &offset) < 0) {
      log_line("segment %d prefix write failed errno=%d", task->index, errno);
      free(buf);
      close(out);
      close(fd);
      segmented_mark_failed(shared, -1);
      return NULL;
    }
    remaining -= (long long)write_len;
    segmented_add_bytes(shared, (long long)write_len);
  }
  while (remaining > 0) {
    if (segmented_should_stop(shared)) {
      task->rc = -6;
      free(buf);
      close(out);
      close(fd);
      return NULL;
    }
    size_t want = SEGMENT_BUFFER_BYTES;
    if ((long long)want > remaining) {
      want = (size_t)remaining;
    }
    ssize_t got = read(fd, buf, want);
    if (got < 0) {
      if (errno == EINTR) {
        continue;
      }
      log_line("segment %d read failed errno=%d offset=%lld", task->index, errno, offset);
      free(buf);
      close(out);
      close(fd);
      segmented_mark_failed(shared, -1);
      return NULL;
    }
    if (got == 0) {
      log_line("segment %d ended early remaining=%lld", task->index, remaining);
      free(buf);
      close(out);
      close(fd);
      segmented_mark_failed(shared, -1);
      return NULL;
    }
    if (pwrite_all_at(out, buf, (size_t)got, &offset) < 0) {
      log_line("segment %d write failed errno=%d offset=%lld", task->index, errno, offset);
      free(buf);
      close(out);
      close(fd);
      segmented_mark_failed(shared, -1);
      return NULL;
    }
    remaining -= got;
    segmented_add_bytes(shared, got);
  }
  free(buf);
  close(out);
  close(fd);
  task->rc = 0;
  log_line("segment %d complete start=%lld end=%lld", task->index, task->start, task->end);
  return NULL;
}

static int http_get_segmented_to_file(download_item_t *item, const char *url, const char *path, long long expected_total, long long *bytes_out, int *status_out) {
  if (expected_total < SEGMENTED_MIN_BYTES) {
    return -7;
  }
  long long existing_final = local_file_size(path);
  if (existing_final == expected_total) {
    if (status_out) {
      *status_out = 200;
    }
    if (bytes_out) {
      *bytes_out = existing_final;
    }
    update_item_bytes(item, existing_final);
    return 0;
  }
  char part_path[MAX_PATH];
  snprintf(part_path, sizeof(part_path), "%s.part", path);
  unlink(part_path);
  int out = open(part_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (out < 0) {
    log_line("segmented open failed path=%s errno=%d", part_path, errno);
    return -1;
  }
  if (ftruncate(out, (off_t)expected_total) < 0) {
    log_line("segmented ftruncate failed path=%s bytes=%lld errno=%d", part_path, expected_total, errno);
    close(out);
    unlink(part_path);
    return -1;
  }
  close(out);

  segmented_shared_t shared;
  memset(&shared, 0, sizeof(shared));
  shared.item = item;
  shared.url = url;
  shared.part_path = part_path;
  shared.expected_total = expected_total;
  shared.next_update = BYTE_UPDATE_STEP;
  pthread_mutex_init(&shared.lock, NULL);

  pthread_t threads[SEGMENTED_CONNECTIONS];
  segment_task_t tasks[SEGMENTED_CONNECTIONS];
  memset(threads, 0, sizeof(threads));
  memset(tasks, 0, sizeof(tasks));
  long long segment_size = expected_total / SEGMENTED_CONNECTIONS;
  long long started_ms = now_ms();
  log_line("segmented download begin url=%s path=%s bytes=%lld connections=%d", url, path, expected_total, SEGMENTED_CONNECTIONS);
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, 512 * 1024);
  int created = 0;
  for (int i = 0; i < SEGMENTED_CONNECTIONS; i++) {
    tasks[i].shared = &shared;
    tasks[i].index = i;
    tasks[i].start = segment_size * i;
    tasks[i].end = (i == SEGMENTED_CONNECTIONS - 1) ? expected_total - 1 : (segment_size * (i + 1)) - 1;
    tasks[i].rc = -1;
    int rc = pthread_create(&threads[i], &attr, segment_worker_main, &tasks[i]);
    if (rc != 0) {
      log_line("segment %d create failed rc=%d", i, rc);
      segmented_mark_failed(&shared, -1);
      break;
    }
    created++;
  }
  pthread_attr_destroy(&attr);
  for (int i = 0; i < created; i++) {
    pthread_join(threads[i], NULL);
  }
  long long total_written = 0;
  int failed = 0;
  int stop_code = 0;
  pthread_mutex_lock(&shared.lock);
  total_written = shared.total_written;
  failed = shared.failed;
  stop_code = shared.stop_code;
  pthread_mutex_unlock(&shared.lock);
  pthread_mutex_destroy(&shared.lock);
  update_item_bytes(item, total_written);
  long long elapsed = now_ms() - started_ms;
  long long kib_s = elapsed > 0 ? (total_written * 1000LL / elapsed / 1024LL) : 0;
  log_line("segmented download end bytes=%lld expected=%lld elapsed_ms=%lld avg_kib_s=%lld failed=%d stop=%d", total_written, expected_total, elapsed, kib_s, failed, stop_code);
  if (status_out) {
    *status_out = 206;
  }
  if (bytes_out) {
    *bytes_out = total_written;
  }
  if (stop_code || failed || total_written != expected_total) {
    unlink(part_path);
    if (stop_code == 1) {
      return -5;
    }
    if (stop_code == 2) {
      return -6;
    }
    return failed ? failed : -1;
  }
  if (rename(part_path, path) < 0) {
    log_line("segmented rename failed %s -> %s errno=%d", part_path, path, errno);
    unlink(part_path);
    return -1;
  }
  return 0;
}

static int http_get_to_file(download_item_t *item, const char *url, const char *path, long long expected_total, int require_ranges, long long *bytes_out, int *status_out, long long limit) {
  parsed_url_t parsed;
  if (parse_http_url(url, &parsed) < 0) {
    return -1;
  }
  if (limit > 0 && expected_total > limit) {
    return -3;
  }
  char part_path[MAX_PATH];
  snprintf(part_path, sizeof(part_path), "%s.part", path);
  long long existing_final = local_file_size(path);
  if (expected_total >= 0 && existing_final == expected_total) {
    if (status_out) {
      *status_out = 200;
    }
    if (bytes_out) {
      *bytes_out = existing_final;
    }
    update_item_bytes(item, existing_final);
    log_line("download already complete path=%s bytes=%lld", path, existing_final);
    return 0;
  }
  long long start = local_file_size(part_path);
  if (start < 0) {
    start = 0;
  }
  if (expected_total >= 0 && start > expected_total) {
    unlink(part_path);
    start = 0;
  }
  if (start > 0 && !require_ranges) {
    log_line("discard partial because server did not advertise range support path=%s bytes=%lld", part_path, start);
    unlink(part_path);
    start = 0;
  }
  if (start == 0 && require_ranges && expected_total >= SEGMENTED_MIN_BYTES) {
    int segmented_status = 0;
    long long segmented_bytes = 0;
    int segmented_rc = http_get_segmented_to_file(item, url, path, expected_total, &segmented_bytes, &segmented_status);
    if (segmented_rc == 0 || segmented_rc == -5 || segmented_rc == -6) {
      if (status_out) {
        *status_out = segmented_status;
      }
      if (bytes_out) {
        *bytes_out = segmented_bytes;
      }
      return segmented_rc;
    }
    log_line("segmented download unavailable rc=%d; falling back to single stream", segmented_rc);
    unlink(part_path);
    start = 0;
  }

  int fd = connect_http(&parsed);
  if (fd < 0) {
    return -1;
  }
  log_line("http get begin url=%s path=%s limit=%lld expected=%lld start=%lld", url, path, limit, expected_total, start);
  char req[MAX_URL + 512];
  int len;
  if (start > 0) {
    len = snprintf(req, sizeof(req),
                   "GET %s HTTP/1.1\r\n"
                   "Host: %s\r\n"
                   "User-Agent: ps5-downloader/0.3-native\r\n"
                   "Range: bytes=%lld-\r\n"
                   "Connection: close\r\n\r\n",
                   parsed.path, parsed.host_header, start);
  } else {
    len = snprintf(req, sizeof(req),
                   "GET %s HTTP/1.1\r\n"
                   "Host: %s\r\n"
                   "User-Agent: ps5-downloader/0.3-native\r\n"
                   "Connection: close\r\n\r\n",
                   parsed.path, parsed.host_header);
  }
  if (len <= 0 || write_all(fd, req, (size_t)len) < 0) {
    close(fd);
    return -1;
  }
  char headers[8192];
  char prefix[4096];
  size_t prefix_len = 0;
  if (read_headers(fd, headers, sizeof(headers), prefix, sizeof(prefix), &prefix_len) < 0) {
    close(fd);
    return -1;
  }
  http_meta_t meta;
  parse_headers(headers, &meta);
  if (status_out) {
    *status_out = meta.status;
  }
  if (start > 0 && meta.status != 206) {
    log_line("range resume refused status=%d start=%lld", meta.status, start);
    close(fd);
    return -4;
  }
  if (start == 0 && (meta.status < 200 || meta.status >= 300)) {
    close(fd);
    return -2;
  }
  if (meta.content_length < 0) {
    log_line("body has unknown response length url=%s start=%lld", url, start);
  }
  if (limit > 0 && meta.content_length >= 0 && start + meta.content_length > limit) {
    log_line("refuse body url=%s response_length=%lld start=%lld limit=%lld", url, meta.content_length, start, limit);
    close(fd);
    return -3;
  }

  int flags = O_WRONLY | O_CREAT;
  flags |= start > 0 ? O_APPEND : O_TRUNC;
  int out = open(part_path, flags, 0644);
  if (out < 0) {
    log_line("open failed: %s errno=%d", part_path, errno);
    close(fd);
    return -1;
  }
  char *buf = malloc(DOWNLOAD_BUFFER_BYTES);
  if (!buf) {
    log_line("download buffer allocation failed bytes=%d", DOWNLOAD_BUFFER_BYTES);
    close(out);
    close(fd);
    return -1;
  }
  long long total = start;
  long long started_ms = now_ms();
  update_item_bytes(item, total);
  if (prefix_len > 0) {
    if (limit > 0 && total + (long long)prefix_len > limit) {
      free(buf);
      close(out);
      close(fd);
      return -3;
    }
    if (write_all(out, prefix, prefix_len) < 0) {
      free(buf);
      close(out);
      close(fd);
      return -1;
    }
    total += (long long)prefix_len;
    update_item_bytes(item, total);
  }
  long long next_log = ((total / PROGRESS_LOG_STEP) + 1) * PROGRESS_LOG_STEP;
  long long next_byte_update = ((total / BYTE_UPDATE_STEP) + 1) * BYTE_UPDATE_STEP;
  log_line("download body begin buffer=%d update_step=%d", DOWNLOAD_BUFFER_BYTES, BYTE_UPDATE_STEP);
  for (;;) {
    int stop = item_stop_requested(item);
    if (stop) {
      log_line("download interrupted state=%s path=%s bytes=%lld", stop == 1 ? "cancelled" : "paused", part_path, total);
      update_item_bytes(item, total);
      free(buf);
      close(out);
      close(fd);
      if (stop == 1) {
        unlink(part_path);
        log_line("cancel removed partial path=%s", part_path);
      }
      if (bytes_out) {
        *bytes_out = total;
      }
      return stop == 1 ? -5 : -6;
    }
    ssize_t got = read(fd, buf, DOWNLOAD_BUFFER_BYTES);
    if (got < 0) {
      if (errno == EINTR) {
        continue;
      }
      log_line("socket read failed errno=%d after=%lld", errno, total);
      update_item_bytes(item, total);
      free(buf);
      close(out);
      close(fd);
      return -1;
    }
    if (got == 0) {
      break;
    }
    if (limit > 0 && total + got > limit) {
      log_line("download exceeded safety limit total=%lld got=%zd limit=%lld", total, got, limit);
      update_item_bytes(item, total);
      free(buf);
      close(out);
      close(fd);
      return -3;
    }
    if (write_all(out, buf, (size_t)got) < 0) {
      log_line("file write failed errno=%d after=%lld", errno, total);
      update_item_bytes(item, total);
      free(buf);
      close(out);
      close(fd);
      return -1;
    }
    total += got;
    if (total >= next_byte_update) {
      update_item_bytes(item, total);
      while (next_byte_update <= total) {
        next_byte_update += BYTE_UPDATE_STEP;
      }
    }
    if (total >= next_log) {
      long long elapsed = now_ms() - started_ms;
      long long kib_s = elapsed > 0 ? ((total - start) * 1000LL / elapsed / 1024LL) : 0;
      log_line("download progress url=%s bytes=%lld expected=%lld speed_kib_s=%lld", url, total, expected_total, kib_s);
      while (next_log <= total) {
        next_log += PROGRESS_LOG_STEP;
      }
    }
  }
  update_item_bytes(item, total);
  long long elapsed = now_ms() - started_ms;
  long long kib_s = elapsed > 0 ? ((total - start) * 1000LL / elapsed / 1024LL) : 0;
  log_line("download body complete bytes=%lld delta=%lld elapsed_ms=%lld avg_kib_s=%lld", total, total - start, elapsed, kib_s);
  free(buf);
  close(out);
  close(fd);
  if (expected_total >= 0 && total != expected_total) {
    log_line("download incomplete total=%lld expected=%lld part=%s", total, expected_total, part_path);
    return -1;
  }
  if (rename(part_path, path) < 0) {
    log_line("rename failed %s -> %s errno=%d", part_path, path, errno);
    return -1;
  }
  if (bytes_out) {
    *bytes_out = total;
  }
  return 0;
}

static int resolve_with_helper(const char *url, char *resolved, size_t resolved_len, char *message, size_t message_len) {
  if (!g_resolver_url[0]) {
    snprintf(message, message_len, "HTTPS/page links need resolver helper; set resolver_url in Settings");
    return -1;
  }
  char encoded[MAX_URL * 2];
  encode_query_value(url, encoded, sizeof(encoded));
  char request_url[MAX_URL * 2];
  const char *sep = strchr(g_resolver_url, '?') ? "&" : "?";
  snprintf(request_url, sizeof(request_url), "%s%surl=%s", g_resolver_url, sep, encoded);
  char response[4096];
  log_line("resolver helper request url=%s", request_url);
  if (http_get_text(request_url, response, sizeof(response)) < 0) {
    snprintf(message, message_len, "resolver helper request failed");
    return -1;
  }
  char urls[1][MAX_URL];
  memset(urls, 0, sizeof(urls));
  if (extract_urls(response, urls, 1) <= 0) {
    if (strstr(response, "manual-action-required")) {
      snprintf(message, message_len, "%.240s", response);
      message[strcspn(message, "\r\n")] = 0;
      log_line("resolver helper manual action response=%.500s", response);
    } else {
      snprintf(message, message_len, "resolver helper returned no direct URL");
      log_line("resolver helper no URL response=%.500s", response);
    }
    return -1;
  }
  snprintf(resolved, resolved_len, "%s", urls[0]);
  snprintf(message, message_len, "resolved through helper");
  log_line("resolver helper returned url=%s", resolved);
  return 0;
}

static int resolve_url(const char *url, char *resolved, size_t resolved_len, char *state, size_t state_len, char *message, size_t message_len) {
  if (starts_with(url, "https://")) {
    if ((starts_with(url, "https://download") && strstr(url, ".mediafire.com/")) ||
        (strstr(url, ".mediafire.com/") && strstr(url, "/download"))) {
      snprintf(resolved, resolved_len, "http://%s", url + 8);
      snprintf(state, state_len, "resolved");
      snprintf(message, message_len, "converted MediaFire direct CDN HTTPS URL to HTTP");
      return 0;
    }
    if (resolve_with_helper(url, resolved, resolved_len, message, message_len) == 0) {
      if (starts_with(resolved, "http://")) {
        snprintf(state, state_len, "resolved");
        return 0;
      }
      snprintf(state, state_len, "manual-action-required");
      snprintf(message, message_len, "resolver helper did not return a PS5-compatible plain HTTP URL");
      return -1;
    }
    if (message[0]) {
      snprintf(state, state_len, "manual-action-required");
      return -1;
    }
    if (strstr(url, "drive.google.com/")) {
      snprintf(state, state_len, "manual-action-required");
      snprintf(message, message_len, "Google Drive did not resolve to a plain HTTP direct file; confirmation, quota, login, or HTTPS-only download may be required");
      return -1;
    }
    if (strstr(url, "mediafire.com/")) {
      snprintf(state, state_len, "manual-action-required");
      return -1;
    }
    snprintf(state, state_len, "manual-action-required");
    snprintf(message, message_len, "HTTPS link could not be converted by the resolver helper to a PS5-compatible plain HTTP URL");
    return -1;
  }
  if (!starts_with(url, "http://")) {
    snprintf(state, state_len, "unsupported");
    snprintf(message, message_len, "only http:// URLs are supported by the native safety build");
    return -1;
  }
  if (g_resolver_url[0] && !strstr(url, "__ps5_host=")) {
    char helper_message[256] = {0};
    if (resolve_with_helper(url, resolved, resolved_len, helper_message, sizeof(helper_message)) == 0) {
      snprintf(state, state_len, "resolved");
      snprintf(message, message_len, "direct HTTP URL normalized through helper");
      return 0;
    }
    log_line("direct HTTP helper normalization skipped url=%s message=%s", url, helper_message);
  }
  snprintf(resolved, resolved_len, "%s", url);
  snprintf(state, state_len, "resolved");
  return 0;
}

static void set_item_state(download_item_t *item, const char *state) {
  pthread_mutex_lock(&g_downloads_lock);
  snprintf(item->state, sizeof(item->state), "%s", state);
  pthread_mutex_unlock(&g_downloads_lock);
}

static void set_item_error(download_item_t *item, const char *state, const char *error) {
  pthread_mutex_lock(&g_downloads_lock);
  snprintf(item->state, sizeof(item->state), "%s", state);
  snprintf(item->error, sizeof(item->error), "%s", error);
  pthread_mutex_unlock(&g_downloads_lock);
}

static void start_worker(void);

static download_item_t *new_download(const char *url) {
  int should_start_worker = 0;
  pthread_mutex_lock(&g_downloads_lock);
  if (g_download_count >= MAX_DOWNLOADS) {
    pthread_mutex_unlock(&g_downloads_lock);
    return NULL;
  }
  download_item_t *item = &g_downloads[g_download_count];
  memset(item, 0, sizeof(*item));
  item->id = g_next_id++;
  snprintf(item->original_url, sizeof(item->original_url), "%s", url);
  snprintf(item->state, sizeof(item->state), "waiting");
  g_download_count++;
  if (!g_worker_started) {
    should_start_worker = 1;
  }
  pthread_mutex_unlock(&g_downloads_lock);
  if (should_start_worker) {
    start_worker();
  }
  return item;
}

static void run_download(download_item_t *item) {
  set_item_state(item, "resolving");
  char resolve_state[64] = {0};
  char message[256] = {0};
  if (resolve_url(item->original_url, item->resolved_url, sizeof(item->resolved_url), resolve_state, sizeof(resolve_state), message, sizeof(message)) < 0) {
    set_item_error(item, resolve_state[0] ? resolve_state : "failed", message);
    log_line("resolve failed id=%d url=%s state=%s message=%s", item->id, item->original_url, item->state, item->error);
    return;
  }

  http_meta_t meta;
  if (http_probe(item->resolved_url, &meta) < 0) {
    set_item_error(item, "failed", "HTTP probe failed");
    log_line("probe failed id=%d url=%s", item->id, item->resolved_url);
    return;
  }
  pthread_mutex_lock(&g_downloads_lock);
  item->http_status = meta.status;
  item->content_length = meta.content_length;
  pthread_mutex_unlock(&g_downloads_lock);
  if (meta.status < 200 || meta.status >= 300) {
    char err[256];
    if (meta.status >= 300 && meta.status < 400 && starts_with(meta.location, "https://")) {
      snprintf(err, sizeof(err), "server redirects plain HTTP to HTTPS; native TLS is disabled for stability");
      set_item_error(item, "manual-action-required", err);
      log_line("probe refused https redirect id=%d status=%d location=%.240s", item->id, meta.status, meta.location);
    } else {
      snprintf(err, sizeof(err), "probe status=%d", meta.status);
      set_item_error(item, "failed", err);
    }
    return;
  }
  if (meta.content_length < 0) {
    log_line("unknown Content-Length allowed id=%d url=%s", item->id, item->resolved_url);
  }
  if (limit_enabled() && meta.content_length > native_limit()) {
    char err[192];
    snprintf(err, sizeof(err), "file is %lld bytes; native safety cap is %lld bytes", meta.content_length, native_limit());
    set_item_error(item, "manual-action-required", err);
    log_line("large file refused id=%d bytes=%lld limit=%lld", item->id, meta.content_length, native_limit());
    return;
  }

  pthread_mutex_lock(&g_downloads_lock);
  if (meta.filename[0]) {
    snprintf(item->filename, sizeof(item->filename), "%s", meta.filename);
  } else {
    sanitize_filename(item->resolved_url, item->filename, sizeof(item->filename));
  }
  snprintf(item->path, sizeof(item->path), "%s/%s", g_download_dir, item->filename);
  snprintf(item->state, sizeof(item->state), "downloading");
  pthread_mutex_unlock(&g_downloads_lock);
  log_line("download start id=%d url=%s path=%s expected=%lld", item->id, item->resolved_url, item->path, meta.content_length);

  int status = 0;
  long long bytes = 0;
  int rc = http_get_to_file(item, item->resolved_url, item->path, meta.content_length, meta.accepts_ranges, &bytes, &status, native_limit());
  pthread_mutex_lock(&g_downloads_lock);
  item->http_status = status;
  item->bytes = bytes;
  if (rc == 0) {
    snprintf(item->state, sizeof(item->state), "completed");
    pthread_mutex_unlock(&g_downloads_lock);
    log_line("download completed id=%d bytes=%lld path=%s", item->id, item->bytes, item->path);
  } else if (rc == -5 || rc == -6) {
    pthread_mutex_unlock(&g_downloads_lock);
    log_line("download stopped id=%d rc=%d bytes=%lld", item->id, rc, bytes);
  } else {
    snprintf(item->state, sizeof(item->state), "failed");
    snprintf(item->error, sizeof(item->error), "download failed rc=%d status=%d", rc, status);
    pthread_mutex_unlock(&g_downloads_lock);
    log_line("download failed id=%d rc=%d status=%d", item->id, rc, status);
  }
}

static void *download_worker_main(void *unused) {
  (void)unused;
  log_line("download worker started");
  for (;;) {
    pthread_mutex_lock(&g_downloads_lock);
    download_item_t *item = NULL;
    for (int i = 0; i < g_download_count; i++) {
      if (!strcmp(g_downloads[i].state, "waiting")) {
        item = &g_downloads[i];
        break;
      }
    }
    pthread_mutex_unlock(&g_downloads_lock);
    if (g_shutdown) {
      break;
    }
    if (item) {
      run_download(item);
    } else {
      usleep(250000);
    }
  }
  log_line("download worker stopped");
  return NULL;
}

static void start_worker(void) {
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, 1024 * 1024);
  int rc = pthread_create(&g_worker_thread, &attr, download_worker_main, NULL);
  pthread_attr_destroy(&attr);
  if (rc == 0) {
    pthread_detach(g_worker_thread);
    g_worker_started = 1;
  } else {
    log_line("download worker create failed rc=%d", rc);
  }
}

static void json_downloads(char *out, size_t out_len) {
  size_t off = 0;
  pthread_mutex_lock(&g_downloads_lock);
  off += snprintf(out + off, out_len - off, "[");
  for (int i = 0; i < g_download_count && i < MAX_DOWNLOADS; i++) {
    download_item_t *d = &g_downloads[i];
    char original[MAX_URL * 2];
    char resolved[MAX_URL * 2];
    char filename[384];
    char path[MAX_PATH * 2];
    char state[96];
    char error[512];
    json_escape(d->original_url, original, sizeof(original));
    json_escape(d->resolved_url, resolved, sizeof(resolved));
    json_escape(d->filename, filename, sizeof(filename));
    json_escape(d->path, path, sizeof(path));
    json_escape(d->state, state, sizeof(state));
    json_escape(d->error, error, sizeof(error));
    off += snprintf(out + off, out_len - off,
                    "%s{\"id\":%d,\"original_url\":\"%s\",\"resolved_url\":\"%s\",\"filename\":\"%s\","
                    "\"path\":\"%s\",\"state\":\"%s\",\"bytes\":%lld,\"content_length\":%lld,\"http_status\":%d,\"error\":\"%s\"}",
                    i ? "," : "", d->id, original, resolved, filename, path,
                    state, d->bytes, d->content_length, d->http_status, error);
    if (off >= out_len) {
      break;
    }
  }
  pthread_mutex_unlock(&g_downloads_lock);
  snprintf(out + off, out_len - off, "]");
}

static void handle_post_links(int client, const char *body) {
  log_line("post links body_prefix=%.160s", body);
  static char urls[MAX_DOWNLOADS][MAX_URL];
  memset(urls, 0, sizeof(urls));
  int url_count = extract_urls(body, urls, MAX_DOWNLOADS);
  if (url_count <= 0) {
    send_response(client, "400 Bad Request", "application/json", "{\"error\":\"no http/https URL found\"}\n");
    return;
  }
  char response[8192];
  if (url_count == 1) {
    download_item_t *item = new_download(urls[0]);
    if (!item) {
      send_response(client, "503 Service Unavailable", "application/json", "{\"error\":\"native queue is full\"}\n");
      return;
    }
    log_line("download item created id=%d url=%s", item->id, urls[0]);
    snprintf(response, sizeof(response),
             "{\"id\":%d,\"state\":\"%s\",\"path\":\"%s\",\"bytes\":%lld,\"content_length\":%lld,\"http_status\":%d,\"error\":\"%s\"}\n",
             item->id, item->state, item->path, item->bytes, item->content_length, item->http_status, item->error);
    send_response(client, "200 OK", "application/json", response);
    return;
  }
  size_t off = 0;
  off += snprintf(response + off, sizeof(response) - off, "{\"count\":%d,\"added\":[", url_count);
  for (int i = 0; i < url_count; i++) {
    download_item_t *item = new_download(urls[i]);
    if (!item) {
      break;
    }
    log_line("download item created id=%d url=%s", item->id, urls[i]);
    off += snprintf(response + off, sizeof(response) - off,
                    "%s{\"id\":%d,\"state\":\"%s\",\"url\":\"%s\"}",
                    i ? "," : "", item->id, item->state, item->original_url);
    if (off >= sizeof(response)) {
      break;
    }
  }
  snprintf(response + off, sizeof(response) - off, "]}\n");
  send_response(client, "200 OK", "application/json", response);
}

static void handle_post_resolve(int client, const char *body) {
  log_line("post resolve body_prefix=%.160s", body);
  char url[MAX_URL] = {0};
  char resolved[MAX_URL] = {0};
  char state[64] = {0};
  char message[256] = {0};
  if (extract_first_url(body, url, sizeof(url)) < 0) {
    send_response(client, "400 Bad Request", "application/json", "{\"error\":\"no http/https URL found\"}\n");
    return;
  }
  int ok = resolve_url(url, resolved, sizeof(resolved), state, sizeof(state), message, sizeof(message));
  char response[4096];
  snprintf(response, sizeof(response),
           "{\"ok\":%s,\"state\":\"%s\",\"original_url\":\"%s\",\"resolved_url\":\"%s\",\"message\":\"%s\"}\n",
           ok == 0 ? "true" : "false", state, url, resolved, message);
  send_response(client, "200 OK", "application/json", response);
}

static int parse_download_path(const char *path, int *id, char *action, size_t action_len) {
  const char *prefix = "/api/downloads/";
  size_t prefix_len = strlen(prefix);
  if (strncmp(path, prefix, prefix_len)) {
    return -1;
  }
  const char *p = path + prefix_len;
  if (!isdigit((unsigned char)*p)) {
    return -1;
  }
  *id = atoi(p);
  const char *slash = strchr(p, '/');
  if (!slash || !slash[1]) {
    action[0] = 0;
    return 0;
  }
  snprintf(action, action_len, "%s", slash + 1);
  return 0;
}

static void send_downloads_json(int client) {
  char body_out[8192];
  json_downloads(body_out, sizeof(body_out));
  send_response(client, "200 OK", "application/json", body_out);
}

static void handle_download_action(int client, const char *method, const char *path) {
  int id = 0;
  char action[32] = {0};
  if (parse_download_path(path, &id, action, sizeof(action)) < 0) {
    send_response(client, "404 Not Found", "application/json", "{\"error\":\"not found\"}\n");
    return;
  }

  pthread_mutex_lock(&g_downloads_lock);
  int index = -1;
  for (int i = 0; i < g_download_count; i++) {
    if (g_downloads[i].id == id) {
      index = i;
      break;
    }
  }
  if (index < 0) {
    pthread_mutex_unlock(&g_downloads_lock);
    send_response(client, "404 Not Found", "application/json", "{\"error\":\"download not found\"}\n");
    return;
  }

  download_item_t *item = &g_downloads[index];
  if (!strcmp(method, "DELETE")) {
    char file_path[MAX_PATH] = {0};
    char part_path[MAX_PATH] = {0};
    if (item->path[0]) {
      snprintf(file_path, sizeof(file_path), "%s", item->path);
      snprintf(part_path, sizeof(part_path), "%s.part", item->path);
    }
    if (!strcmp(item->state, "downloading") || !strcmp(item->state, "resolving")) {
      snprintf(item->state, sizeof(item->state), "cancelled");
      snprintf(item->error, sizeof(item->error), "delete requested while active; item will remain until stopped");
      pthread_mutex_unlock(&g_downloads_lock);
      if (file_path[0]) {
        unlink_download_path(part_path, "partial", id);
        unlink_download_path(file_path, "final", id);
      }
      log_line("download delete requested active id=%d", id);
      send_downloads_json(client);
      return;
    }
    for (int i = index; i + 1 < g_download_count; i++) {
      g_downloads[i] = g_downloads[i + 1];
    }
    g_download_count--;
    pthread_mutex_unlock(&g_downloads_lock);
    if (file_path[0]) {
      unlink_download_path(part_path, "partial", id);
      unlink_download_path(file_path, "final", id);
    }
    log_line("download deleted id=%d removed_file=%s", id, file_path[0] ? file_path : "");
    send_downloads_json(client);
    return;
  }

  if (!strcmp(action, "pause")) {
    if (!strcmp(item->state, "waiting") || !strcmp(item->state, "resolving") || !strcmp(item->state, "downloading")) {
      snprintf(item->state, sizeof(item->state), "paused");
      snprintf(item->error, sizeof(item->error), "paused by user");
    }
  } else if (!strcmp(action, "cancel")) {
    if (!strcmp(item->state, "completed")) {
      snprintf(item->error, sizeof(item->error), "already completed; use delete to remove the file");
    } else {
      snprintf(item->state, sizeof(item->state), "cancelled");
      snprintf(item->error, sizeof(item->error), "cancelled by user");
      if (item->path[0]) {
        char part_path[MAX_PATH];
        snprintf(part_path, sizeof(part_path), "%s.part", item->path);
        unlink(part_path);
        log_line("cancel removed partial id=%d path=%s", id, part_path);
      }
    }
  } else if (!strcmp(action, "start") || !strcmp(action, "resume")) {
    if (strcmp(item->state, "downloading") && strcmp(item->state, "resolving") && strcmp(item->state, "completed")) {
      snprintf(item->state, sizeof(item->state), "waiting");
      item->error[0] = 0;
    }
  } else {
    pthread_mutex_unlock(&g_downloads_lock);
    send_response(client, "404 Not Found", "application/json", "{\"error\":\"unknown action\"}\n");
    return;
  }
  pthread_mutex_unlock(&g_downloads_lock);
  log_line("download action id=%d action=%s", id, action[0] ? action : method);
  send_downloads_json(client);
}

static void handle_put_settings(int client, const char *body) {
  char new_dir[MAX_PATH] = {0};
  char new_resolver[MAX_URL] = {0};
  char *key = strcasestr_local(body, "download_dir");
  if (!key) {
    key = strcasestr_local(body, "downloadDir");
  }
  if (key) {
    char *p = strchr(key, ':');
    if (!p) {
      p = strchr(key, '=');
    }
    if (p) {
      p++;
      while (*p == ' ' || *p == '"' || *p == '\'') {
        p++;
      }
      size_t i = 0;
      while (p[i] && p[i] != '"' && p[i] != '\'' && p[i] != '&' && p[i] != '\r' && p[i] != '\n' && p[i] != '}' && i + 1 < sizeof(new_dir)) {
        new_dir[i] = p[i];
        i++;
      }
      new_dir[i] = 0;
    }
  } else if (body[0] == '/') {
    snprintf(new_dir, sizeof(new_dir), "%s", body);
    new_dir[strcspn(new_dir, "\r\n")] = 0;
  }
  char *resolver_key = strcasestr_local(body, "resolver_url");
  if (!resolver_key) {
    resolver_key = strcasestr_local(body, "resolverUrl");
  }
  if (resolver_key) {
    char *p = strchr(resolver_key, ':');
    if (!p) {
      p = strchr(resolver_key, '=');
    }
    if (p) {
      p++;
      while (*p == ' ' || *p == '"' || *p == '\'') {
        p++;
      }
      size_t i = 0;
      while (p[i] && p[i] != '"' && p[i] != '\'' && p[i] != '&' && p[i] != '\r' && p[i] != '\n' && p[i] != '}' && i + 1 < sizeof(new_resolver)) {
        new_resolver[i] = p[i];
        i++;
      }
      new_resolver[i] = 0;
    }
  }
  if (!validate_download_dir(new_dir)) {
    send_response(client, "400 Bad Request", "application/json", "{\"error\":\"download_dir must be under /data and cannot contain ..\"}\n");
    return;
  }
  if (new_resolver[0] && !starts_with(new_resolver, "http://")) {
    send_response(client, "400 Bad Request", "application/json", "{\"error\":\"resolver_url must be blank or start with http://\"}\n");
    return;
  }
  snprintf(g_download_dir, sizeof(g_download_dir), "%s", new_dir);
  if (resolver_key) {
    snprintf(g_resolver_url, sizeof(g_resolver_url), "%s", new_resolver);
  }
  ensure_download_dir();
  save_config();
  char escaped[MAX_PATH * 2];
  char escaped_resolver[MAX_URL * 2];
  char response[1024];
  json_escape(g_download_dir, escaped, sizeof(escaped));
  json_escape(g_resolver_url, escaped_resolver, sizeof(escaped_resolver));
  snprintf(response, sizeof(response), "{\"ok\":true,\"download_dir\":\"%s\",\"resolver_url\":\"%s\"}\n", escaped, escaped_resolver);
  log_line("settings updated download_dir=%s resolver_url=%s", g_download_dir, g_resolver_url);
  send_response(client, "200 OK", "application/json", response);
}

static void send_log_file(int client, const char *path, const char *label) {
  FILE *fp = fopen(path, "r");
  if (!fp) {
    char body[256];
    snprintf(body, sizeof(body), "log unavailable: %s errno=%d\n", label, errno);
    send_response(client, "200 OK", "text/plain", body);
    return;
  }
  static char body[LOG_RESPONSE_BYTES + 1];
  long started_mid_file = 0;
  if (fseek(fp, 0, SEEK_END) == 0) {
    long size = ftell(fp);
    if (size > LOG_RESPONSE_BYTES) {
      fseek(fp, size - LOG_RESPONSE_BYTES, SEEK_SET);
      started_mid_file = 1;
    } else {
      fseek(fp, 0, SEEK_SET);
    }
  }
  size_t got = fread(body, 1, sizeof(body) - 1, fp);
  fclose(fp);
  body[got] = 0;
  if (started_mid_file && got > 0) {
    char *first_full_line = strchr(body, '\n');
    if (first_full_line && first_full_line[1]) {
      memmove(body, first_full_line + 1, strlen(first_full_line + 1) + 1);
    }
  }
  send_response(client, "200 OK", "text/plain; charset=utf-8", body);
}

static void send_diagnostics(int client) {
  char body[2048];
  char escaped_resolver[MAX_URL * 2];
  json_escape(g_resolver_url, escaped_resolver, sizeof(escaped_resolver));
  snprintf(body, sizeof(body),
           "{\"ok\":true,\"log_paths\":["
           "{\"name\":\"ps5-downloader\",\"path\":\"%s\",\"size\":%lld},"
           "{\"name\":\"nanoDNS\",\"path\":\"%s\",\"size\":%lld},"
           "{\"name\":\"pid\",\"path\":\"%s\",\"size\":%lld}],"
           "\"download_dir\":\"%s\",\"resolver_url\":\"%s\","
           "\"notes\":[\"/dev/klog requires a separate klog reader such as klogsrv or loader support\","
           "\"Only fixed known log paths are exposed; arbitrary file reads are intentionally not supported\"]}\n",
           LOG_PATH, file_size_or_negative(LOG_PATH),
           NANODNS_LOG_PATH, file_size_or_negative(NANODNS_LOG_PATH),
           PID_PATH, file_size_or_negative(PID_PATH),
           g_download_dir, escaped_resolver);
  send_response(client, "200 OK", "application/json", body);
}

static void handle_client(int client) {
  char request[4096 + MAX_BODY];
  ssize_t got = read(client, request, sizeof(request) - 1);
  if (got <= 0) {
    return;
  }
  request[got] = 0;
  char *header_end = strstr(request, "\r\n\r\n");
  if (header_end) {
    long long content_length = 0;
    char *cl = strcasestr_local(request, "\nContent-Length:");
    if (cl && cl < header_end) {
      content_length = atoll(cl + strlen("\nContent-Length:"));
    }
    size_t header_bytes = (size_t)(header_end + 4 - request);
    long long needed = (long long)header_bytes + content_length;
    if (content_length > MAX_BODY) {
      send_response(client, "413 Payload Too Large", "application/json", "{\"error\":\"request body too large\"}\n");
      return;
    }
    while (needed > got && got < (ssize_t)sizeof(request) - 1) {
      ssize_t more = read(client, request + got, sizeof(request) - 1 - (size_t)got);
      if (more < 0) {
        if (errno == EINTR) {
          continue;
        }
        break;
      }
      if (more == 0) {
        break;
      }
      got += more;
      request[got] = 0;
    }
  }
  char method[12] = {0};
  char path[256] = {0};
  sscanf(request, "%11s %255s", method, path);
  log_line("request method=%s path=%s bytes=%zd", method, path, got);
  char *body = strstr(request, "\r\n\r\n");
  body = body ? body + 4 : request + got;

  if (!strncmp(request, "OPTIONS ", 8)) {
    send_response(client, "204 No Content", "text/plain", "");
    log_response(method, path, "204");
  } else if (!strncmp(request, "GET /api/status ", 16)) {
    char body_out[2048];
    char escaped_dir[MAX_PATH * 2];
    char escaped_resolver[MAX_URL * 2];
    json_escape(g_download_dir, escaped_dir, sizeof(escaped_dir));
    json_escape(g_resolver_url, escaped_resolver, sizeof(escaped_resolver));
    snprintf(body_out, sizeof(body_out),
             "{\"ok\":true,\"native\":true,\"safety_build\":true,\"name\":\"ps5-downloader\","
             "\"port\":%d,\"max_native_download_bytes\":%lld,\"queue_max\":%d,\"worker_started\":%s,"
             "\"segmented_connections\":%d,\"download_dir\":\"%s\",\"resolver_url\":\"%s\",\"log\":\"/data/test/ps5-downloader.log\"}\n",
             PS5_DOWNLOADER_PORT, native_limit(), MAX_DOWNLOADS, g_worker_started ? "true" : "false", SEGMENTED_CONNECTIONS, escaped_dir, escaped_resolver);
    send_response(client, "200 OK", "application/json", body_out);
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/settings ", 18)) {
    char escaped_dir[MAX_PATH * 2];
    char escaped_resolver[MAX_URL * 2];
    char body_out[1024];
    json_escape(g_download_dir, escaped_dir, sizeof(escaped_dir));
    json_escape(g_resolver_url, escaped_resolver, sizeof(escaped_resolver));
    snprintf(body_out, sizeof(body_out),
             "{\"download_dir\":\"%s\",\"temp_dir\":\"%s\",\"resolver_url\":\"%s\",\"max_concurrent_downloads\":1,"
             "\"per_download_connections\":%d,\"user_agent\":\"ps5-downloader/0.3-native\",\"https_enabled\":false,"
             "\"max_native_download_bytes\":0,"
             "\"note\":\"native build: plain HTTP only, queued downloads, no fixed size cap\"}\n",
             escaped_dir, escaped_dir, escaped_resolver, SEGMENTED_CONNECTIONS);
    send_response(client, "200 OK", "application/json", body_out);
    log_response(method, path, "200");
  } else if (!strncmp(request, "PUT /api/settings ", 18)) {
    handle_put_settings(client, body);
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/plugins ", 17)) {
    send_response(client, "200 OK", "application/json",
                  "[{\"name\":\"direct-http-socket-safe\",\"supports_metadata\":true},"
                  "{\"name\":\"https-manual-required\",\"supports_metadata\":false}]\n");
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/logs ", 14)) {
    send_log_file(client, LOG_PATH, "ps5-downloader");
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/logs/self ", 19)) {
    send_log_file(client, LOG_PATH, "ps5-downloader");
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/logs/nanodns ", 22)) {
    send_log_file(client, NANODNS_LOG_PATH, "nanoDNS");
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/diagnostics ", 21)) {
    send_diagnostics(client);
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET /api/downloads ", 19)) {
    send_downloads_json(client);
    log_response(method, path, "200");
  } else if (!strncmp(request, "POST /api/downloads/", 20)) {
    handle_download_action(client, method, path);
    log_response(method, path, "200");
  } else if (!strncmp(request, "DELETE /api/downloads/", 22)) {
    handle_download_action(client, method, path);
    log_response(method, path, "200");
  } else if (!strncmp(request, "POST /api/links ", 16)) {
    handle_post_links(client, body);
    log_response(method, path, "200");
  } else if (!strncmp(request, "POST /api/resolve ", 18)) {
    handle_post_resolve(client, body);
    log_response(method, path, "200");
  } else if (!strncmp(request, "POST /api/shutdown ", 19) || !strncmp(request, "POST /api/prepare-reload ", 25)) {
    g_shutdown = 1;
    send_response(client, "200 OK", "application/json", "{\"ok\":true,\"message\":\"shutting down\"}\n");
    log_response(method, path, "200");
  } else if (!strncmp(request, "GET / ", 6) || !strncmp(request, "GET /index.html ", 16)) {
    send_response(client, "200 OK", "application/json",
                  "{\"ok\":true,\"name\":\"ps5-downloader\",\"mode\":\"api-only\","
                  "\"message\":\"Use the desktop app or REST API to control downloads.\"}\n");
    log_response(method, path, "200");
  } else {
    send_response(client, "404 Not Found", "application/json", "{\"error\":\"not found\"}\n");
    log_response(method, path, "404");
  }
}

static int create_server(void) {
  int server = socket(AF_INET, SOCK_STREAM, 0);
  if (server < 0) {
    return -1;
  }
  int yes = 1;
  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(PS5_DOWNLOADER_PORT);
  if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    close(server);
    return -1;
  }
  if (listen(server, 8) < 0) {
    close(server);
    return -1;
  }
  return server;
}

static void write_pid_file(void) {
  FILE *fp = fopen(PID_PATH, "w");
  if (fp) {
    fprintf(fp, "%d\n", getpid());
    fclose(fp);
  }
}

int main(void) {
  signal(SIGPIPE, SIG_IGN);
  mkdir(DATA_ROOT, 0755);
  load_config();
  ensure_download_dir();
  write_pid_file();
  log_line("ps5-downloader native queue build starting pid=%d port=%d max_bytes=%lld queue_max=%d", getpid(), PS5_DOWNLOADER_PORT, native_limit(), MAX_DOWNLOADS);
  log_line("diagnostic paths self=%s nanodns=%s pid=%s", LOG_PATH, NANODNS_LOG_PATH, PID_PATH);
  int server = create_server();
  if (server < 0) {
    log_line("server bind failed port=%d errno=%d", PS5_DOWNLOADER_PORT, errno);
    return EXIT_FAILURE;
  }
  log_line("server listening on port %d, download_dir=/data/test, max_bytes=%d", PS5_DOWNLOADER_PORT, MAX_NATIVE_DOWNLOAD_BYTES);
  for (; !g_shutdown;) {
    int client = accept(server, NULL, NULL);
    if (client < 0) {
      if (errno == EINTR) {
        continue;
      }
      break;
    }
    handle_client(client);
    close(client);
  }
  close(server);
  g_shutdown = 1;
  unlink(PID_PATH);
  log_line("server stopped");
  return EXIT_SUCCESS;
}
