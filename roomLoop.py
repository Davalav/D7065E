

result =""

for i in range(143,154):
    result += '''
        {
            "name": "'''+str(i)+ '''",
            "floor": 0,
            "walls": 2.3
        },'''
        
print(result)