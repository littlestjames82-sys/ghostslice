const express = require('express');
const axios = require('axios');
const { shout } = require('./util');

const app = express();
app.get('/', (req, res) => res.send(shout('ok')));
module.exports = { app, axios };
