class ProactiveManager {
    constructor(app) {
        this.app = app;
        this.pollTimer = null;
    }

    start(intervalMs = 30000) {
        this.stop();
        this.pollTimer = setInterval(() => this.poll(), intervalMs);
    }

    stop() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }

    async poll() {
        try {
            const pending = await API.getProactivePending();
            if (pending && pending.content) {
                this.app.onProactiveMessage(pending);
                // Browser notification if tab hidden
                if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
                    new Notification('Memoria', { body: pending.content.slice(0, 100) });
                }
            }
        } catch (e) {
            // Silent fail for polling
        }
    }
}
