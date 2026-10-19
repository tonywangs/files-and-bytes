const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'./tests',testMatch:'*.spec.js',workers:1,reporter:'list',outputDir:'/tmp/atlas-browser-artifacts',use:{headless:true},webServer:{command:'python3 -m atlas .demo/zlib-1.3.1 --port 4173',url:'http://127.0.0.1:4173',reuseExistingServer:false}});
