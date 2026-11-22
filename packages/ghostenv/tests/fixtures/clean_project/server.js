// Clean fixture server (JS side): names match .env / .env.example.
// Values are FAKE test placeholders only, never real credentials.
const region = process.env.APP_REGION || "us-east-1";
const port = process.env.APP_PORT || 8000;
module.exports = { region, port };
