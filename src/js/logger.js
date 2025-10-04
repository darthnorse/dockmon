/**
 * DockMon Logging Utility
 * Centralized logging with environment-based levels
 */

const LogLevel = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3,
    NONE: 4
};

class Logger {
    constructor() {
        // Set log level based on environment or default to INFO for production
        this.level = this.getLogLevel();
    }

    getLogLevel() {
        // Default to WARN level (only show warnings and errors)
        return LogLevel.WARN;
    }

    debug(...args) {
        if (this.level <= LogLevel.DEBUG) {
            console.log('[DEBUG]', ...args);
        }
    }

    info(...args) {
        if (this.level <= LogLevel.INFO) {
            console.info('[INFO]', ...args);
        }
    }

    warn(...args) {
        if (this.level <= LogLevel.WARN) {
            console.warn('[WARN]', ...args);
        }
    }

    error(...args) {
        if (this.level <= LogLevel.ERROR) {
            console.error('[ERROR]', ...args);
        }
    }

    // For WebSocket/Network debugging
    ws(...args) {
        if (this.level <= LogLevel.DEBUG) {
            console.log('[WS]', ...args);
        }
    }

    // For API debugging
    api(...args) {
        if (this.level <= LogLevel.DEBUG) {
            console.log('[API]', ...args);
        }
    }
}

// Create singleton instance
const logger = new Logger();

// Make available globally
window.logger = logger;
