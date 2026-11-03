
self.addEventListener("push", (event) => {
  let data = {};

  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {
      title: "K124",
      body: event.data ? event.data.text() : "Tienes un aviso nuevo."
    };
  }

  const title = data.title || "K124";
  const options = {
    body: data.body || "Tienes un aviso nuevo.",
    icon: "./icon-192.png",
    badge: "./icon-192.png",
    tag: data.tag || "k124-aviso",
    renotify: false,
    data: {
      url: data.url || "./"
    }
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const target = new URL(
    event.notification.data?.url || "./",
    self.location.origin
  ).href;

  event.waitUntil(
    clients.matchAll({
      type: "window",
      includeUncontrolled: true
    }).then((windows) => {
      for (const window of windows) {
        if (window.url.startsWith(self.location.origin) &&
            "focus" in window) {
          window.navigate(target);
          return window.focus();
        }
      }

      return clients.openWindow(target);
    })
  );
});
