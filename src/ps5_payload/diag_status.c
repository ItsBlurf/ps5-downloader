#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#ifdef DIAG_PTHREAD
#include <pthread.h>
#endif
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#ifndef DIAG_PORT
#define DIAG_PORT 2644
#endif

static volatile int g_shutdown = 0;
static volatile int g_thread_seen = 0;

#ifdef DIAG_PTHREAD
static void *diag_thread(void *unused) {
  (void)unused;
  g_thread_seen = 1;
  while (!g_shutdown) {
    usleep(100000);
  }
  return NULL;
}
#endif

static void write_all(int fd, const char *data, size_t len) {
  while (len > 0) {
    ssize_t n = write(fd, data, len);
    if (n <= 0) {
      return;
    }
    data += n;
    len -= (size_t)n;
  }
}

static void respond(int client, const char *body) {
  char header[256];
  int n = snprintf(header, sizeof(header),
                   "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                   "Content-Length: %zu\r\nConnection: close\r\n\r\n",
                   strlen(body));
  write_all(client, header, (size_t)n);
  write_all(client, body, strlen(body));
}

int main(void) {
  signal(SIGPIPE, SIG_IGN);
#ifdef DIAG_PTHREAD
  pthread_t thread;
  if (pthread_create(&thread, NULL, diag_thread, NULL) == 0) {
    pthread_detach(thread);
  }
#endif
  int server = socket(AF_INET, SOCK_STREAM, 0);
  if (server < 0) {
    return 1;
  }
  int yes = 1;
  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(DIAG_PORT);
  if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    return 2;
  }
  if (listen(server, 4) < 0) {
    return 3;
  }
  while (!g_shutdown) {
    int client = accept(server, NULL, NULL);
    if (client < 0) {
      if (errno == EINTR) {
        continue;
      }
      break;
    }
    char req[512];
    ssize_t got = read(client, req, sizeof(req) - 1);
    if (got > 0) {
      req[got] = 0;
      if (!strncmp(req, "POST /api/shutdown ", 19)) {
        g_shutdown = 1;
        respond(client, "{\"ok\":true,\"diag\":true,\"shutdown\":true}\n");
      } else {
        respond(client, g_thread_seen ? "{\"ok\":true,\"diag\":true,\"pthread\":true}\n" : "{\"ok\":true,\"diag\":true,\"pthread\":false}\n");
      }
    }
    close(client);
  }
  close(server);
  return 0;
}
