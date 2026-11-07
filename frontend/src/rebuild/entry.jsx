import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import OperationalApp from './OperationalApp.jsx';
const Root = import.meta.env.VITE_API_MODE === 'operational' ? OperationalApp : App;
createRoot(document.getElementById('root')).render(<Root/>);
