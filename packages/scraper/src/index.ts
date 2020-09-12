import {config} from 'dotenv';
config();
config({path: '../../.env'});

import './lib';
import './publisher';
import './scraper';
