import {config} from 'dotenv';
config();
config({path: '../../.env'});

import './infrastructure';
import './models';
import './analyzer';
