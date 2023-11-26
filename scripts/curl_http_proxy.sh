set -ex
curl --proxy http://a:b@127.0.0.1:8080 https://baidu.com -v
curl --proxy http://a:b@127.0.0.1:8080 http://baidu.com -v
curl --proxy http://a:b@127.0.0.1:8080 http://1.1.1.1 -v
curl --proxy http://a:b@127.0.0.1:8080 https://1.1.1.1 -v