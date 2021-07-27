import {config} from 'dotenv';
config();
config({path: '../../.env'});

import './infrastructure';
import './publisher';
import './scraper';
import './scheduler';
import './models';
