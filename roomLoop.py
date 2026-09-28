

result =""

for i in range(112,131):
    result += '''
        {
            "name": "A'''+str(i)+ '''",
            "floor": 0,
            "walls": 2.3
        },'''
        
print(result)