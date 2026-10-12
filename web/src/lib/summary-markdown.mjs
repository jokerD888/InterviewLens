import raw from "rehype-raw";
import sanitize from "rehype-sanitize";

// Sanitize AFTER parsing raw HTML. Keep Markdown formatting and sub counts.
export const summaryPlugins = [raw, sanitize];
